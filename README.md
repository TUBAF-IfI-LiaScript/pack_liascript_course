# pack_liascript_course

A Python tool that packs a [LiaScript](https://liascript.github.io/) course — a Markdown file together with all of its relative local dependencies — into a single ZIP archive.

## Features

- Accepts a **local Markdown file**, a **direct URL**, or a **GitHub repository URL** as source.
- Automatically discovers and bundles relative assets referenced in the course: images, stylesheets, scripts, audio/video files, and LiaScript `@import` macros.
- GitHub repository URLs default to `README.md` on the default branch (resolved via the special `HEAD` ref, so it works with both `main` and `master` branches).
- GitHub blob URLs (`github.com/.../blob/...`) are automatically converted to their `raw.githubusercontent.com` equivalents.
- Missing or inaccessible assets produce a warning but do not abort the packaging.
- Optionally moves the finished ZIP to an upload destination.

## Installation

```bash
pip install pack-liascript-course
```

Or with [pipx](https://pipx.pypa.io/) for an isolated global install:

```bash
pipx install pack-liascript-course
```

## CLI Usage

```
pack-liascript-course <source> [-o OUTPUT] [--upload DEST]
```

### Arguments

| Argument | Description |
|---|---|
| `source` | Source of the LiaScript course (local file path, URL, or GitHub repository URL). |
| `-o`, `--output OUTPUT` | Output ZIP file path. Defaults to `<stem>.zip` next to the source file (or the current directory for URLs). |
| `--upload DEST` | Move the generated ZIP to `DEST` after creation. `DEST` may be a file path or a directory. |

### Examples

**Pack a local Markdown file:**
```bash
pack-liascript-course path/to/course.md
```

**Pack from a direct URL:**
```bash
pack-liascript-course https://example.com/courses/intro.md
```

**Pack from a GitHub repository (uses `README.md` on the default branch):**
```bash
pack-liascript-course https://github.com/user/my-liascript-course
```

**Pack from a specific file in a GitHub repository:**
```bash
pack-liascript-course https://github.com/user/repo/blob/main/course.md
```

**Specify a custom output path:**
```bash
pack-liascript-course course.md -o dist/my_course.zip
```

**Pack and upload to a deployment directory:**
```bash
pack-liascript-course course.md --upload /var/www/courses/
```

## Python API

The `pack_course` function can also be used directly in Python:

```python
from pack_liascript_course import pack_liascript_course as packer

zip_path = packer.pack_course(
    source="path/to/course.md",  # local file, URL, or GitHub repo URL
    output="dist/course.zip",    # optional; defaults to <stem>.zip next to source
    upload="/var/www/courses/",  # optional; moves the ZIP to this path/directory
)
print(f"ZIP created at: {zip_path}")
```

## What gets packed

The tool scans the Markdown source for relative asset references and includes them in the ZIP, preserving the original directory structure:

- Markdown images: `![alt](path)`
- Markdown links: `[text](path)`
- HTML `<img src="...">`, `<link href="...">`, `<script src="...">`
- HTML `<audio>`, `<video>`, and `<source>` elements
- LiaScript macro imports: `@import 'macros.md'`

Only relative paths are included; absolute URLs (starting with `http://`, `https://`, `//`, etc.) are left unchanged.

## License

[CC0-1.0](LICENSE)
