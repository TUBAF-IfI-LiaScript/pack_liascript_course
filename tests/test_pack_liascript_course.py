"""Tests for pack_liascript_course.py"""

import os
import shutil
import tempfile
import textwrap
import zipfile
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from pack_liascript_course import pack_liascript_course as packer


# ---------------------------------------------------------------------------
# URL helper tests
# ---------------------------------------------------------------------------

class TestIsUrl:
    def test_http(self):
        assert packer.is_url("http://example.com/course.md")

    def test_https(self):
        assert packer.is_url("https://example.com/course.md")

    def test_local_path(self):
        assert not packer.is_url("/path/to/file.md")

    def test_relative_path(self):
        assert not packer.is_url("course.md")


class TestIsGithubRepoUrl:
    def test_repo_root(self):
        assert packer.is_github_repo_url("https://github.com/user/repo")

    def test_repo_root_trailing_slash(self):
        assert packer.is_github_repo_url("https://github.com/user/repo/")

    def test_blob_url(self):
        assert not packer.is_github_repo_url(
            "https://github.com/user/repo/blob/main/README.md"
        )

    def test_non_github(self):
        assert not packer.is_github_repo_url("https://example.com/user/repo")


class TestGithubBlobToRaw:
    def test_converts_correctly(self):
        url = "https://github.com/user/repo/blob/main/docs/course.md"
        expected = "https://raw.githubusercontent.com/user/repo/main/docs/course.md"
        assert packer.github_blob_to_raw(url) == expected

    def test_branch_with_slash(self):
        url = "https://github.com/user/repo/blob/feature/branch/file.md"
        expected = "https://raw.githubusercontent.com/user/repo/feature/branch/file.md"
        assert packer.github_blob_to_raw(url) == expected


class TestGithubRepoToReadmeUrl:
    def test_readme_url(self):
        url = packer.github_repo_to_readme_url("https://github.com/alice/my-course")
        assert url == "https://raw.githubusercontent.com/alice/my-course/HEAD/README.md"


class TestResolveSourceUrl:
    def test_local_file(self):
        fetch_url, base_url = packer.resolve_source_url("/path/to/course.md")
        assert fetch_url == "/path/to/course.md"
        assert base_url == ""

    def test_direct_url(self):
        fetch_url, base_url = packer.resolve_source_url(
            "https://example.com/courses/intro.md"
        )
        assert fetch_url == "https://example.com/courses/intro.md"
        assert base_url == "https://example.com/courses/"

    def test_github_repo(self):
        fetch_url, base_url = packer.resolve_source_url("https://github.com/user/repo")
        assert fetch_url == "https://raw.githubusercontent.com/user/repo/HEAD/README.md"
        assert base_url == "https://raw.githubusercontent.com/user/repo/HEAD/"

    def test_github_blob(self):
        fetch_url, base_url = packer.resolve_source_url(
            "https://github.com/user/repo/blob/main/course.md"
        )
        assert fetch_url == "https://raw.githubusercontent.com/user/repo/main/course.md"
        assert base_url == "https://raw.githubusercontent.com/user/repo/main/"


# ---------------------------------------------------------------------------
# Dependency extraction tests
# ---------------------------------------------------------------------------

class TestExtractRelativeLinks:
    def test_markdown_image(self):
        content = "![diagram](images/diagram.png)"
        links = packer.extract_relative_links(content)
        assert "images/diagram.png" in links

    def test_markdown_link(self):
        content = "[download](resources/file.pdf)"
        links = packer.extract_relative_links(content)
        assert "resources/file.pdf" in links

    def test_html_img(self):
        content = '<img src="assets/photo.jpg" alt="photo">'
        links = packer.extract_relative_links(content)
        assert "assets/photo.jpg" in links

    def test_html_link_stylesheet(self):
        content = '<link rel="stylesheet" href="styles/custom.css">'
        links = packer.extract_relative_links(content)
        assert "styles/custom.css" in links

    def test_html_script(self):
        content = '<script src="js/quiz.js"></script>'
        links = packer.extract_relative_links(content)
        assert "js/quiz.js" in links

    def test_liascript_import(self):
        content = "@import 'macros.md'"
        links = packer.extract_relative_links(content)
        assert "macros.md" in links

    def test_liascript_import_double_quotes(self):
        content = '@import "https://example.com/remote.md"'
        links = packer.extract_relative_links(content)
        assert "https://example.com/remote.md" not in links

    def test_skips_absolute_urls(self):
        content = "![logo](https://example.com/logo.png)"
        links = packer.extract_relative_links(content)
        assert not links

    def test_skips_fragment_only(self):
        content = "[section](#introduction)"
        links = packer.extract_relative_links(content)
        assert not links

    def test_strips_query_and_fragment(self):
        content = "![img](images/photo.png?v=2#section)"
        links = packer.extract_relative_links(content)
        assert "images/photo.png" in links

    def test_deduplication(self):
        content = "![a](img.png)\n![b](img.png)"
        links = packer.extract_relative_links(content)
        assert links.count("img.png") == 1

    def test_mixed_content(self):
        content = textwrap.dedent("""\
            # My Course

            ![diagram](images/diagram.svg)

            <link rel="stylesheet" href="css/style.css">

            See [this](https://external.com) for more.
            Also check [local](notes.md).
        """)
        links = packer.extract_relative_links(content)
        assert "images/diagram.svg" in links
        assert "css/style.css" in links
        assert "notes.md" in links
        # External URL must be excluded
        assert not any(l.startswith("http") for l in links)


# ---------------------------------------------------------------------------
# Pack course – local files
# ---------------------------------------------------------------------------

class TestPackCourseLocal:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, rel_path: str, content: str) -> Path:
        p = self.tmpdir / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_simple_markdown_no_deps(self):
        md = self._write("course.md", "# Hello LiaScript")
        zip_path = packer.pack_course(str(md))
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "course.md" in names
            assert zf.read("course.md") == b"# Hello LiaScript"

    def test_with_image_dependency(self):
        content = "![img](images/photo.png)"
        md = self._write("course.md", content)
        self._write("images/photo.png", "PNGDATA")

        zip_path = packer.pack_course(str(md))
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "course.md" in names
            assert "images/photo.png" in names

    def test_with_css_dependency(self):
        content = '<link rel="stylesheet" href="styles/custom.css">'
        md = self._write("course.md", content)
        self._write("styles/custom.css", "body { color: red; }")

        zip_path = packer.pack_course(str(md))
        with zipfile.ZipFile(zip_path) as zf:
            assert "styles/custom.css" in zf.namelist()

    def test_missing_dependency_is_warned_not_fatal(self, capsys):
        content = "![missing](missing.png)"
        md = self._write("course.md", content)

        zip_path = packer.pack_course(str(md))
        assert zip_path.exists()
        captured = capsys.readouterr()
        assert "Warning" in captured.err

    def test_custom_output_path(self):
        md = self._write("course.md", "# Test")
        out = self.tmpdir / "subdir" / "output.zip"
        zip_path = packer.pack_course(str(md), output=str(out))
        assert zip_path == out
        assert out.exists()

    def test_default_zip_name(self):
        md = self._write("my_course.md", "# Test")
        zip_path = packer.pack_course(str(md))
        assert zip_path.name == "my_course.zip"
        assert zip_path.parent == self.tmpdir

    def test_upload_to_directory(self):
        md = self._write("course.md", "# Test")
        upload_dir = self.tmpdir / "uploads"
        upload_dir.mkdir()

        final = packer.pack_course(str(md), upload=str(upload_dir))
        assert final == upload_dir / "course.zip"
        assert final.exists()

    def test_upload_to_file_path(self):
        md = self._write("course.md", "# Test")
        upload_path = self.tmpdir / "out" / "packed.zip"

        final = packer.pack_course(str(md), upload=str(upload_path))
        assert final == upload_path
        assert final.exists()

    def test_upload_moves_zip(self):
        md = self._write("course.md", "# Test")
        upload_dir = self.tmpdir / "uploads"
        upload_dir.mkdir()

        packer.pack_course(str(md), upload=str(upload_dir))
        # Original zip location should no longer exist
        original_zip = self.tmpdir / "course.zip"
        assert not original_zip.exists()


# ---------------------------------------------------------------------------
# Pack course – URL source (mocked network)
# ---------------------------------------------------------------------------

class TestPackCourseUrl:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _mock_fetch_bytes(self, url_map: dict[str, bytes]):
        """Return a side_effect function for patching fetch_bytes."""
        def _fetch(url):
            if url in url_map:
                return url_map[url]
            raise RuntimeError(f"Unexpected URL: {url}")
        return _fetch

    def test_direct_url(self):
        md_url = "https://example.com/courses/intro.md"
        asset_url = "https://example.com/courses/images/pic.png"
        url_map = {
            md_url: b"![pic](images/pic.png)",
            asset_url: b"PNGDATA",
        }
        out = self.tmpdir / "intro.zip"

        with patch.object(packer, "fetch_bytes", side_effect=self._mock_fetch_bytes(url_map)):
            zip_path = packer.pack_course(md_url, output=str(out))

        with zipfile.ZipFile(zip_path) as zf:
            assert "intro.md" in zf.namelist()
            assert "images/pic.png" in zf.namelist()

    def test_github_repo_url(self):
        readme_url = "https://raw.githubusercontent.com/user/repo/HEAD/README.md"
        url_map = {readme_url: b"# My Course\n![img](img.png)"}
        img_url = "https://raw.githubusercontent.com/user/repo/HEAD/img.png"
        url_map[img_url] = b"IMGDATA"
        out = self.tmpdir / "README.zip"

        with patch.object(packer, "fetch_bytes", side_effect=self._mock_fetch_bytes(url_map)):
            zip_path = packer.pack_course("https://github.com/user/repo", output=str(out))

        with zipfile.ZipFile(zip_path) as zf:
            assert "README.md" in zf.namelist()
            assert "img.png" in zf.namelist()

    def test_github_blob_url(self):
        raw_url = "https://raw.githubusercontent.com/user/repo/main/course.md"
        url_map = {raw_url: b"# Course"}
        out = self.tmpdir / "course.zip"

        with patch.object(packer, "fetch_bytes", side_effect=self._mock_fetch_bytes(url_map)):
            zip_path = packer.pack_course(
                "https://github.com/user/repo/blob/main/course.md",
                output=str(out),
            )

        with zipfile.ZipFile(zip_path) as zf:
            assert "course.md" in zf.namelist()

    def test_failed_asset_does_not_abort(self, capsys):
        md_url = "https://example.com/course.md"
        url_map = {md_url: b"![img](missing.png)"}
        out = self.tmpdir / "course.zip"

        def fetch_raises(url):
            if url == md_url:
                return url_map[url]
            raise RuntimeError("Not found")

        with patch.object(packer, "fetch_bytes", side_effect=fetch_raises):
            zip_path = packer.pack_course(md_url, output=str(out))

        assert zip_path.exists()
        captured = capsys.readouterr()
        assert "Warning" in captured.err


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_basic_invocation(self):
        md = self.tmpdir / "course.md"
        md.write_text("# Test", encoding="utf-8")
        packer.main([str(md)])
        assert (self.tmpdir / "course.zip").exists()

    def test_output_flag(self):
        md = self.tmpdir / "course.md"
        md.write_text("# Test", encoding="utf-8")
        out = self.tmpdir / "custom.zip"
        packer.main([str(md), "-o", str(out)])
        assert out.exists()

    def test_upload_flag(self):
        md = self.tmpdir / "course.md"
        md.write_text("# Test", encoding="utf-8")
        upload_dir = self.tmpdir / "dest"
        upload_dir.mkdir()
        packer.main([str(md), "--upload", str(upload_dir)])
        assert (upload_dir / "course.zip").exists()

    def test_missing_source_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc_info:
            packer.main(["/nonexistent/course.md"])
        assert exc_info.value.code != 0
