"""The second copy, in ~/Downloads.

Everything you save exists twice: once in the library, where the application
reads it, and once in Downloads, where *you* can get at it without this program
installed. The Downloads copy is a self-contained .html with its images inlined
-- double-click it, read it on a plane, mail it to someone.

Filenames carry the capture's 8-character URL hash. The library can afford
title-derived names because it has a manifest behind every note and can detect
and repair collisions; a flat mirror directory has neither. Two pages that
happen to share a title, or one page that gets retitled between captures, would
otherwise silently overwrite or orphan a file in a directory you did not ask
this program to manage. With the hash, re-saving the same URL is an idempotent
overwrite and two different URLs can never land on the same name.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .capture.compile import CompileError, compile_html
from .capture.paths import safe_filename
from .config import DOWNLOADS_MIRROR


@dataclass
class MirrorResult:
    note: Path | None = None
    page: Path | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.note is not None


def capture_digest(capture_dir: Path) -> str:
    """The stable URL hash the capture directory is named with."""
    return capture_dir.name.rsplit("-", 1)[-1]


def mirror_name(title: str, capture_dir: Path) -> str:
    return f"{safe_filename(title)}-{capture_digest(capture_dir)}"


def mirror_capture(
    *,
    capture_dir: Path,
    note_path: Path,
    title: str,
    topic: str,
    root: Path | None = None,
) -> MirrorResult:
    """Copy a finished capture into the Downloads mirror.

    Never fatal. A failure here means one convenience copy is missing, which
    should not take down the save that already succeeded in the library -- so
    the error is returned for reporting rather than raised.
    """
    target_dir = (root or DOWNLOADS_MIRROR) / topic
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return MirrorResult(error=f"could not create {target_dir}: {exc}")

    stem = mirror_name(title, capture_dir)
    result = MirrorResult()

    try:
        note_copy = target_dir / f"{stem}.md"
        shutil.copy2(note_path, note_copy)
        result.note = note_copy
    except OSError as exc:
        return MirrorResult(error=f"could not copy the note: {exc}")

    # The self-contained page is the point of the mirror, but it is also the
    # part that can fail on a capture with no page.html (a plain .txt upload,
    # say). A missing page is not a failed mirror.
    try:
        result.page = compile_html(capture_dir, target_dir / f"{stem}.html")
    except (CompileError, OSError) as exc:
        result.error = f"note copied, page not built: {exc}"

    return result


def prune_stale(*, title: str, capture_dir: Path, topic: str,
                root: Path | None = None) -> None:
    """Remove a mirrored pair left behind when a page changes title.

    The hash keeps the *new* name stable and collision-free, but a retitled
    page still leaves its old name sitting there. The digest is what identifies
    the pair as belonging to this capture, so anything sharing the digest and
    not matching the current name is a leftover.
    """
    target_dir = (root or DOWNLOADS_MIRROR) / topic
    if not target_dir.is_dir():
        return
    digest = capture_digest(capture_dir)
    keep = mirror_name(title, capture_dir)
    for path in target_dir.glob(f"*-{digest}.*"):
        if path.stem != keep and path.suffix in {".md", ".html"}:
            try:
                path.unlink()
            except OSError:
                pass
