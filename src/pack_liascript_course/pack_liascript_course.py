#!/usr/bin/env python3
"""pack_liascript_course.py

Pack a LiaScript course (a Markdown file and its relative dependencies)
into a ZIP archive.

Usage:
    python pack_liascript_course.py <source> [-o OUTPUT] [--upload DEST]

<source> can be:
  - A local path to a Markdown file
  - A direct URL to a Markdown file
  - A GitHub repository URL (defaults to README.md on the default branch)
"""

import argparse
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse, urljoin
import urllib.request
import urllib.error


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def is_url(path: str) -> bool:
    """Return True if *path* looks like an HTTP(S) URL."""
    try:
        result = urlparse(path)
        return result.scheme in ("http", "https")
    except ValueError:
        return False


def is_github_repo_url(url: str) -> bool:
    """Return True if *url* is a GitHub repository root (not a blob/raw link)."""
    parsed = urlparse(url)
    if parsed.netloc not in ("github.com", "www.github.com"):
        return False
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    # A repo root has exactly two path segments: user/repo
    return len(parts) == 2


def github_blob_to_raw(url: str) -> str:
    """Convert a github.com /blob/ URL to its raw.githubusercontent.com equivalent."""
    # https://github.com/user/repo/blob/branch/path/to/file.md
    # -> https://raw.githubusercontent.com/user/repo/branch/path/to/file.md
    parsed = urlparse(url)
    path = parsed.path  # e.g. /user/repo/blob/branch/path/to/file.md
    raw_path = path.replace("/blob/", "/", 1)
    return f"https://raw.githubusercontent.com{raw_path}"


def github_repo_to_readme_url(repo_url: str) -> str:
    """Return the raw URL for README.md in a GitHub repository.

    Uses the special ``HEAD`` ref so it works regardless of whether the default
    branch is *main* or *master*.
    """
    parsed = urlparse(repo_url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    user, repo = parts[0], parts[1]
    return f"https://raw.githubusercontent.com/{user}/{repo}/HEAD/README.md"


def resolve_source_url(source: str) -> tuple[str, str]:
    """Resolve *source* to a (fetch_url, base_url) pair.

    *fetch_url* is the URL used to download the main Markdown file.
    *base_url* is the directory URL used to resolve relative asset links.
    """
    if is_github_repo_url(source):
        fetch_url = github_repo_to_readme_url(source)
    elif is_url(source):
        parsed = urlparse(source)
        # Convert github.com /blob/ links to raw content
        if parsed.netloc in ("github.com", "www.github.com") and "/blob/" in parsed.path:
            fetch_url = github_blob_to_raw(source)
        else:
            fetch_url = source
    else:
        fetch_url = source  # local path

    if is_url(fetch_url):
        base_url = fetch_url.rsplit("/", 1)[0] + "/"
    else:
        base_url = ""

    return fetch_url, base_url


# ---------------------------------------------------------------------------
# Content fetching
# ---------------------------------------------------------------------------

def fetch_bytes(source: str) -> bytes:
    """Fetch raw bytes from a local path or URL."""
    if is_url(source):
        try:
            with urllib.request.urlopen(source) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} fetching {source}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot fetch {source}: {exc.reason}") from exc
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {source}")
        return path.read_bytes()


# ---------------------------------------------------------------------------
# Dependency extraction
# ---------------------------------------------------------------------------

# Patterns that may reference relative asset files in a LiaScript/Markdown doc.
_LINK_PATTERNS = [
    # Markdown image:  ![alt](path)
    re.compile(r'!\[[^\]]*\]\(([^)\s]+)\)'),
    # Markdown link:   [text](path)  (negative lookbehind avoids double-match with images)
    re.compile(r'(?<!!)\[[^\]]*\]\(([^)\s]+)\)'),
    # HTML img src
    re.compile(r'<img\b[^>]+\bsrc=["\']([^"\']+)["\']', re.IGNORECASE),
    # HTML link href (stylesheets)
    re.compile(r'<link\b[^>]+\bhref=["\']([^"\']+)["\']', re.IGNORECASE),
    # HTML script src
    re.compile(r'<script\b[^>]+\bsrc=["\']([^"\']+)["\']', re.IGNORECASE),
    # LiaScript @import
    re.compile(r'@import\s+["\']([^"\']+)["\']', re.IGNORECASE),
    # HTML audio/video src
    re.compile(r'<(?:audio|video|source)\b[^>]+\bsrc=["\']([^"\']+)["\']', re.IGNORECASE),
]

_ABSOLUTE_PREFIXES = ("http://", "https://", "//", "#", "mailto:", "data:")


def extract_relative_links(content: str) -> list[str]:
    """Return a deduplicated list of relative asset paths referenced in *content*."""
    seen: set[str] = set()
    result: list[str] = []

    for pattern in _LINK_PATTERNS:
        for match in pattern.finditer(content):
            raw = match.group(1).strip()
            # Remove query string and fragment
            path = raw.split("?")[0].split("#")[0].strip()
            if not path:
                continue
            # Skip absolute links
            if any(path.startswith(prefix) for prefix in _ABSOLUTE_PREFIXES):
                continue
            if path not in seen:
                seen.add(path)
                result.append(path)

    return result


# ---------------------------------------------------------------------------
# Core packing logic
# ---------------------------------------------------------------------------

def pack_course(source: str, output: str | None = None, upload: str | None = None) -> Path:
    """Pack *source* (and its relative dependencies) into a ZIP file.

    Parameters
    ----------
    source:
        Local file path, direct URL, or GitHub repository URL.
    output:
        Destination ZIP path.  When *None* the ZIP is created next to the
        source file (or in the current working directory for URLs).
    upload:
        If given, the finished ZIP is *moved* to this path (file or directory).

    Returns
    -------
    Path
        The final location of the ZIP file.
    """
    fetch_url, base_url = resolve_source_url(source)
    source_is_url = is_url(fetch_url)

    # Determine the filename used for the main markdown file inside the ZIP
    if source_is_url:
        filename = PurePosixPath(urlparse(fetch_url).path).name or "README.md"
        default_output_dir = Path.cwd()
    else:
        source_path = Path(fetch_url).resolve()
        filename = source_path.name
        default_output_dir = source_path.parent

    stem = Path(filename).stem

    # Determine output zip path
    if output is None:
        zip_path = default_output_dir / f"{stem}.zip"
    else:
        zip_path = Path(output)

    # Fetch main markdown content
    print(f"Fetching: {fetch_url}")
    content_bytes = fetch_bytes(fetch_url)
    content_text = content_bytes.decode("utf-8", errors="replace")

    # Extract relative asset links
    relative_links = extract_relative_links(content_text)

    # Build ZIP
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, content_bytes)
        print(f"  Added: {filename}")

        for link in relative_links:
            try:
                if source_is_url:
                    asset_url = urljoin(base_url, link)
                    print(f"  Fetching: {asset_url}")
                    asset_bytes = fetch_bytes(asset_url)
                else:
                    asset_path = source_path.parent / link
                    if not asset_path.exists():
                        print(f"  Warning: dependency not found, skipping: {link}", file=sys.stderr)
                        continue
                    print(f"  Adding: {link}")
                    asset_bytes = asset_path.read_bytes()

                # Preserve the relative directory structure inside the ZIP
                zf.writestr(link, asset_bytes)
            except Exception as exc:
                print(f"  Warning: could not include {link}: {exc}", file=sys.stderr)

    print(f"ZIP created: {zip_path}")

    # Handle upload (move the ZIP to a specified destination)
    if upload:
        dest = Path(upload)
        # Treat as a directory when it already is one, or the given string has a
        # trailing separator (e.g. "/some/dir/")
        if dest.is_dir() or upload.endswith(os.sep) or upload.endswith("/"):
            dest.mkdir(parents=True, exist_ok=True)
            dest = dest / zip_path.name
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(zip_path), str(dest))
        print(f"Uploaded to: {dest}")
        return dest

    return zip_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pack_liascript_course",
        description=(
            "Pack a LiaScript course (Markdown file + relative dependencies) "
            "into a ZIP archive."
        ),
    )
    parser.add_argument(
        "source",
        help=(
            "Source of the LiaScript course.  Can be: "
            "(1) a local path to a Markdown file, "
            "(2) a direct URL to a Markdown file, or "
            "(3) a GitHub repository URL (README.md is used by default)."
        ),
    )
    parser.add_argument(
        "-o", "--output",
        metavar="OUTPUT",
        default=None,
        help=(
            "Output ZIP file path.  Defaults to <stem>.zip in the same "
            "directory as the source file (or the current directory for URLs)."
        ),
    )
    parser.add_argument(
        "--upload",
        metavar="DEST",
        default=None,
        help=(
            "Move the generated ZIP to DEST after creation.  DEST may be a "
            "file path or a directory."
        ),
    )

    args = parser.parse_args(argv)

    try:
        pack_course(args.source, args.output, args.upload)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
