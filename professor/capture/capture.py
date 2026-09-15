"""Writing a capture to disk.

Layout, and the reasoning behind it:

    python-University/
       python-Lecture/                     <- where a bare `-python` lands
          Primer on Python Decorators.md      the note you actually read
          Primer on Python Decorators-a1b2c3d4.html   self-contained copy
       async-Lecture/                      <- from `-python.async`
       .captures/
          realpython-decorators-a1b2c3d4/
             page.html        reconstruction, relative asset refs
             assets/          normalised images
             manifest.json    url, title, tier, source, asset map
             original.html    raw post-JS DOM, to re-extract without refetching

Notes are split into lectures, but .captures/ deliberately is not: the archive
is the same artifact whichever lecture chose to keep it, and holding it at one
fixed depth is what lets find_capture() stay a single-level glob and lets two
lectures share an image-heavy capture without a second copy.

The capture directory is named from a **stable hash of the URL**, not the date.
That is what makes re-capture an overwrite rather than an accumulation: the
same URL always lands on the same path, so there is nothing to search for.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .assets import collect_image_urls, download_assets
from .extract import extract
from .fetch import FetchResult
from .paths import (
    captures_dir_for_lecture,
    ensure_lecture,
    safe_filename,
    slugify,
)

# Who chose this material. The user's own references are what Professor-Claude
# teaches from first; anything it fetched itself to fill a gap is marked so it
# can be weighted lower and shown separately.
SOURCE_USER = "user"
SOURCE_CLAUDE = "claude"

MANIFEST_NAME = "manifest.json"


@dataclass
class CaptureResult:
    note_path: Path
    capture_dir: Path
    title: str
    tier: str
    word_count: int
    assets_kept: int
    assets_failed: int
    updated: bool
    from_archive: bool = False
    source: str = SOURCE_USER


def capture_slug(url: str) -> str:
    """A stable, readable directory name for a URL.

    Readable prefix so you can tell what a directory is at a glance; hash
    suffix so two different URLs never collide and the *same* URL always
    resolves to the same directory.
    """
    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.").split(":")[0]
    path = parsed.path.strip("/")
    readable = slugify(f"{host.split('.')[0]}-{path.replace('/', '-')}", max_len=48)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"{readable}-{digest}"


def _rewrite_html_assets(soup: BeautifulSoup, mapping: dict[str, str],
                         base_url: str) -> None:
    """Point the archived HTML at its local copies, so it opens offline."""

    def local(value: str | None) -> str | None:
        if not value:
            return None
        absolute = urljoin(base_url, value.strip())
        filename = mapping.get(absolute) or mapping.get(value.strip())
        return f"assets/{filename}" if filename else None

    for img in soup.find_all("img"):
        replacement = local(img.get("data-mfp-src")) or local(img.get("src"))
        if not replacement and img.get("srcset"):
            first = img["srcset"].split(",")[0].strip().split(" ")[0]
            replacement = local(first)
        if replacement:
            img["src"] = replacement
            # srcset would otherwise override the src we just rewrote.
            for attr in ("srcset", "data-src", "data-mfp-src", "loading"):
                img.attrs.pop(attr, None)

    for source in soup.find_all("source"):
        if source.get("srcset"):
            first = source["srcset"].split(",")[0].strip().split(" ")[0]
            replacement = local(first)
            if replacement:
                source["srcset"] = replacement

    for el in soup.select("[data-mfp-bg]"):
        replacement = local(el.get("data-mfp-bg"))
        if replacement:
            existing = el.get("style", "")
            el["style"] = f"{existing};background-image:url('{replacement}')"

    # Embeds can't be archived; leave a card naming what was there.
    for frame in soup.find_all("iframe"):
        src = frame.get("src") or ""
        card = soup.new_tag("div")
        card["style"] = (
            "border:1px solid #999;border-radius:8px;padding:16px;margin:16px 0;"
            "font-family:system-ui,sans-serif;font-size:14px;"
        )
        card.string = f"[embedded content not archived] {src}"
        frame.replace_with(card)


def _existing_manifest(capture_dir: Path) -> dict | None:
    path = capture_dir / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _note_is_claimed(lecture_dir: Path, note_name: str, exclude: Path) -> bool:
    """Does some *other* capture already own this note filename?

    Overwriting is keyed on the URL, not the title -- so two different URLs
    that happen to share a title (per-version doc pages, wire stories, and
    anything falling back to "Untitled") must not land on the same note. Left
    unchecked the second capture silently destroys the first one's note, which
    is the only file the user actually reads.
    """
    captures = captures_dir_for_lecture(lecture_dir)
    if not captures.is_dir():
        return False
    for sibling in captures.iterdir():
        if not sibling.is_dir() or sibling.resolve() == exclude.resolve():
            continue
        manifest = _existing_manifest(sibling)
        if manifest and manifest.get("note") == note_name:
            # One .captures/ now serves every lecture under a university, so a
            # name is only actually taken if the capture holding it files into
            # this same lecture. Two lectures may each have their own Index.md.
            if manifest.get("topic", "").endswith(f"/{lecture_dir.name}"):
                return True
    return False


def _resolve_note_name(lecture_dir: Path, title: str, capture_dir: Path,
                       prior: dict | None) -> str:
    """Pick this capture's note filename, disambiguating on collision."""
    desired = f"{safe_filename(title)}.md"

    # Our own previous note under this exact name: reclaim it.
    if prior and prior.get("note") == desired:
        return desired

    # A file already sitting under that name in the lecture counts as taken,
    # even with no manifest behind it -- the user can drop a .md in by hand,
    # and clobbering it would be the same data loss the manifest check exists
    # to prevent.
    on_disk = (lecture_dir / desired).exists()

    taken = _note_is_claimed(lecture_dir, desired, capture_dir) or (
        on_disk and not (prior and prior.get("note") == desired)
    )
    if not taken:
        return desired

    # Reuse the capture directory's URL hash, so the same URL always resolves
    # to the same note name rather than accumulating -1, -2 suffixes.
    digest = capture_dir.name.rsplit("-", 1)[-1]
    return f"{safe_filename(title)}-{digest}.md"


def write_capture(result: FetchResult, *, lecture_dir: Path, topic: str,
                  original_url: str, quiet: bool = False,
                  source: str = SOURCE_USER) -> CaptureResult:
    """Archive a fetched page, replacing any previous capture of the same URL.

    The note lands in `lecture_dir`; the archive lands in the .captures/ of the
    university above it. `source` is recorded in the manifest as a fact about
    who chose the material, and no longer decides where anything is written.
    """
    ensure_lecture(lecture_dir)
    slug = capture_slug(original_url)
    capture_dir = captures_dir_for_lecture(lecture_dir) / slug

    prior = _existing_manifest(capture_dir)
    updated = prior is not None

    # Replace wholesale rather than merging -- old assets may no longer be
    # referenced, and a half-updated capture is worse than a clean one.
    if capture_dir.exists():
        shutil.rmtree(capture_dir)
    (capture_dir / "assets").mkdir(parents=True, exist_ok=True)

    (capture_dir / "original.html").write_text(result.html, encoding="utf-8")

    soup = BeautifulSoup(result.html, "lxml")
    image_urls = collect_image_urls(soup, result.final_url, result.background_images)
    report = download_assets(image_urls, capture_dir / "assets", quiet=quiet)

    extraction = extract(
        result.html,
        original_url,
        capture_slug=slug,
        asset_mapping=report.mapping,
        topic=topic,
        tier=result.tier,
        from_archive=result.from_archive,
    )

    _rewrite_html_assets(soup, report.mapping, result.final_url)
    (capture_dir / "page.html").write_text(str(soup), encoding="utf-8")

    note_name = _resolve_note_name(lecture_dir, extraction.title, capture_dir, prior)
    note_path = lecture_dir / note_name

    # A retitled page would otherwise leave its old note orphaned beside the
    # new one; the manifest is what lets us find and remove it. Only remove a
    # note this capture actually owned -- never one another capture claims.
    #
    if prior and prior.get("note") and prior["note"] != note_name:
        if not _note_is_claimed(lecture_dir, prior["note"], capture_dir):
            stale = lecture_dir / prior["note"]
            if stale.exists():
                stale.unlink()

    note_path.write_text(extraction.markdown, encoding="utf-8")

    manifest = {
        "url": original_url,
        "final_url": result.final_url,
        "title": extraction.title,
        "author": extraction.byline,
        "site": extraction.site,
        "topic": topic,
        "note": note_name,
        "source": source,
        "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tier": result.tier,
        "from_archive": result.from_archive,
        "archive_timestamp": result.archive_timestamp,
        "word_count": extraction.word_count,
        "assets_kept": report.kept,
        "assets_failed": report.failed,
        "assets_dropped": report.dropped,
        "assets": report.mapping,
    }
    (capture_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return CaptureResult(
        note_path=note_path,
        capture_dir=capture_dir,
        title=extraction.title,
        tier=result.tier,
        word_count=extraction.word_count,
        assets_kept=report.kept,
        assets_failed=report.failed,
        updated=updated,
        from_archive=result.from_archive,
        source=source,
    )
