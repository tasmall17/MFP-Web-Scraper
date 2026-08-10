"""Local files in: .md, .txt, .pdf.

The capture layer only knows how to fetch. This is the other door into the
library, and the important thing about it is that it produces **exactly the
same bundle** a fetched page does -- a readable note in the references
directory, a `.captures/<slug>/` archive with `page.html`, `assets/`,
`manifest.json`, and a copy of what came in. Everything downstream (the
syllabus, the reading pane, the Downloads mirror, Professor-Claude's context)
then has one shape to deal with instead of two.

The capture slug is a stable hash of the filename, mirroring the way a fetched
capture hashes its URL. Re-uploading `chapter-3.pdf` overwrites the previous
`chapter-3.pdf` rather than accumulating copies, which is almost always what
someone re-uploading a file means.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .capture.assets import MAX_ASSETS, MIN_DIMENSION, _normalise
from .capture.capture import SOURCE_USER, CaptureResult, MANIFEST_NAME
from .capture.paths import (
    CAPTURES_DIR,
    captures_dir,
    ensure_topic_layout,
    refs_dir_for,
    safe_filename,
    slugify,
)
from .markdown import split_frontmatter, to_html

SUPPORTED = {".md", ".markdown", ".txt", ".text", ".pdf"}

# Enough of a page to be worth a lesson. Below this it's a stub, and the
# syllabus is better off not pretending otherwise.
MIN_USEFUL_WORDS = 20


class IngestError(Exception):
    pass


@dataclass
class _Parsed:
    title: str
    body: str
    assets: dict[str, str]
    pages: int = 0


# ---------------------------------------------------------------- addressing

def local_slug(filename: str) -> str:
    """A stable, readable capture directory name for an uploaded file.

    Same shape as the fetched-page slug -- readable prefix so you can tell what
    it is at a glance, hash suffix so re-uploading the same name lands in the
    same place and two different names never collide.
    """
    stem = Path(filename).stem
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:8]
    return f"{slugify(stem, max_len=48)}-{digest}"


def _yaml_escape(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


# ------------------------------------------------------------------ handlers

def _parse_markdown(data: bytes, filename: str) -> _Parsed:
    text = data.decode("utf-8", errors="replace")
    meta, body = split_frontmatter(text)

    title = meta.get("title", "").strip()
    if not title:
        heading = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = heading.group(1).strip() if heading else Path(filename).stem

    # The first H1 becomes the note's own title line, so leaving it in the body
    # renders it twice.
    body = re.sub(r"^#\s+.+\n+", "", body.lstrip(), count=1)
    return _Parsed(title=title, body=body.strip(), assets={})


def _parse_text(data: bytes, filename: str) -> _Parsed:
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    # Plain text is rendered as prose rather than a code block: study material
    # arriving as .txt is overwhelmingly prose or lightly-structured notes, and
    # a monospace wall is much worse to read than the occasional line that
    # happens to look like Markdown.
    return _Parsed(title=Path(filename).stem, body=text.strip(), assets={})


def _pdf_images(reader, assets_dir: Path) -> dict[str, str]:
    """Pull embedded images out of a PDF, normalised like fetched assets.

    Reuses the capture layer's `_normalise` so an image from a PDF and an image
    from a web page are the same kind of thing by the time anything else sees
    them: PNG, downscaled, icons and rules discarded.
    """
    assets_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    seen: set[str] = set()
    index = 0

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            images = list(page.images)
        except Exception:
            # A malformed image stream shouldn't cost us the whole document.
            continue
        for image in images:
            if index >= MAX_ASSETS:
                return mapping
            try:
                raw = image.data
            except Exception:
                continue
            normalised = _normalise(raw, Path(image.name or "img.png").suffix or ".png")
            if not normalised:
                continue
            payload, ext, (width, height) = normalised
            if width < MIN_DIMENSION or height < MIN_DIMENSION:
                continue
            digest = hashlib.sha256(payload).hexdigest()[:8]
            if digest in seen:
                continue
            seen.add(digest)
            index += 1
            name = f"img-{index:03d}-{digest}{ext}"
            (assets_dir / name).write_bytes(payload)
            mapping[f"p{page_number}-{image.name}"] = name

    return mapping


def _parse_pdf(data: bytes, filename: str, assets_dir: Path) -> _Parsed:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise IngestError("pypdf is required to read PDFs") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise IngestError(f"could not read the PDF: {exc}") from exc

    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            raise IngestError(
                "this PDF is password-protected -- unlock it and upload it again"
            ) from None

    title = ""
    try:
        title = (reader.metadata.title or "").strip() if reader.metadata else ""
    except Exception:
        title = ""
    title = title or Path(filename).stem

    chunks: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = re.sub(r"[ \t]+\n", "\n", text).strip()
        if not text:
            continue
        # A visible page marker is worth the noise: it is how you cross-check
        # what Professor-Claude says against the PDF sitting on your desk.
        chunks.append(f"## Page {number}\n\n{text}")

    assets = _pdf_images(reader, assets_dir)
    if assets:
        chunks.append("## Figures\n")
        chunks += [f"![Figure {i}](assets/{name})"
                   for i, name in enumerate(assets.values(), start=1)]

    return _Parsed(
        title=title,
        body="\n\n".join(chunks).strip(),
        assets=assets,
        pages=len(reader.pages),
    )


# -------------------------------------------------------------------- ingest

def _note_markdown(*, title: str, body: str, filename: str, topic: str,
                   slug: str, source: str, pages: int) -> str:
    """Build the note, matching the frontmatter a fetched capture writes."""
    fields = [
        ("title", _yaml_escape(title)),
        ("origin", _yaml_escape(filename)),
        ("captured", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("topic", _yaml_escape(topic)),
        ("source", source),
    ]
    if pages:
        fields.append(("pages", str(pages)))
    fields.append(("tags", "[mfp/upload]"))

    # In the note, asset links have to reach down into the hidden archive; in
    # page.html, which lives inside it, they are relative. Same body text, two
    # different vantage points.
    note_body = body.replace("](assets/", f"]({CAPTURES_DIR}/{slug}/assets/")

    # No attribution line: `origin` is already in the frontmatter, and the
    # reading pane shows it in the header. A visible "uploaded from X" would
    # just repeat it directly above the text.
    lines = ["---"]
    lines += [f"{key}: {value}" for key, value in fields]
    lines += ["---", "", f"# {title}", "", note_body, ""]
    return "\n".join(lines) + "\n"


_PAGE_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{max-width:44rem;margin:3rem auto;padding:0 1.25rem;
font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,sans-serif;
color:#1c1917}}
img{{max-width:100%;height:auto;border-radius:6px}}
pre{{background:#f5f5f4;padding:1rem;border-radius:8px;overflow-x:auto}}
code{{font-size:.9em}}
pre code{{font-size:.85em}}
blockquote{{margin:0;padding-left:1rem;border-left:3px solid #d6d3d1;color:#57534e}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #e7e5e4;padding:.4rem .6rem;text-align:left}}
</style></head>
<body><article><h1>{title}</h1>{body}</article></body></html>
"""


def ingest_file(*, data: bytes, filename: str, topic_dir: Path, topic: str,
                source: str = SOURCE_USER) -> CaptureResult:
    """Turn an uploaded file into a capture bundle. Returns a CaptureResult."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise IngestError(
            f"{suffix or 'that file type'} isn't supported yet -- "
            f"try {', '.join(sorted(SUPPORTED))}"
        )
    if not data:
        raise IngestError("that file is empty")

    ensure_topic_layout(topic_dir)
    slug = local_slug(filename)
    capture_dir = captures_dir(topic_dir) / slug

    prior = None
    manifest_path = capture_dir / MANIFEST_NAME
    if manifest_path.is_file():
        try:
            prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prior = None

    # Replace wholesale, exactly as a re-fetch does: a half-updated capture is
    # worse than a clean one.
    if capture_dir.exists():
        shutil.rmtree(capture_dir)
    (capture_dir / "assets").mkdir(parents=True, exist_ok=True)

    if suffix == ".pdf":
        parsed = _parse_pdf(data, filename, capture_dir / "assets")
    elif suffix in {".txt", ".text"}:
        parsed = _parse_text(data, filename)
    else:
        parsed = _parse_markdown(data, filename)

    word_count = len(parsed.body.split())
    if word_count < MIN_USEFUL_WORDS:
        shutil.rmtree(capture_dir, ignore_errors=True)
        raise IngestError(
            f"only {word_count} words of readable text came out of {filename}. "
            "If it's a scanned PDF it will need OCR first."
        )

    # The original, kept for the same reason a fetched capture keeps its raw
    # DOM: so the note can be rebuilt without going back to the source. For a
    # PDF it is also what gets handed to Claude when a question is about a
    # figure that survived the text extraction badly.
    (capture_dir / f"original{suffix}").write_bytes(data)

    (capture_dir / "page.html").write_text(
        _PAGE_TEMPLATE.format(title=parsed.title, body=to_html(parsed.body)),
        encoding="utf-8",
    )

    note_name = f"{safe_filename(parsed.title)}.md"
    note_path = refs_dir_for(topic_dir, source) / note_name
    note_path.write_text(
        _note_markdown(
            title=parsed.title, body=parsed.body, filename=filename,
            topic=topic, slug=slug, source=source, pages=parsed.pages,
        ),
        encoding="utf-8",
    )

    if prior and prior.get("note") and prior["note"] != note_name:
        stale = refs_dir_for(topic_dir, prior.get("source", source)) / prior["note"]
        if stale.exists():
            stale.unlink()

    manifest = {
        "url": f"local:{filename}",
        "final_url": f"local:{filename}",
        "title": parsed.title,
        "author": None,
        "site": "upload",
        "topic": topic,
        "note": note_name,
        "source": source,
        "origin": "upload",
        "original_filename": filename,
        "original_file": f"original{suffix}",
        "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tier": "local",
        "from_archive": False,
        "archive_timestamp": None,
        "word_count": word_count,
        "pages": parsed.pages,
        "assets_kept": len(parsed.assets),
        "assets_failed": 0,
        "assets_dropped": 0,
        "assets": parsed.assets,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return CaptureResult(
        note_path=note_path,
        capture_dir=capture_dir,
        title=parsed.title,
        tier="local",
        word_count=word_count,
        assets_kept=len(parsed.assets),
        assets_failed=0,
        updated=prior is not None,
        source=source,
    )
