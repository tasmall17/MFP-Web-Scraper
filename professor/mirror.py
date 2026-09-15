"""The portable copy, in the lecture folder.

Everything you save exists twice: once as the Markdown note you read and edit,
and once as a self-contained .html with its images inlined -- double-click it,
read it on a plane, mail it to someone, open it in ten years without this
program installed. Both sit in the same lecture directory, so the material
travels as one folder you can copy anywhere.

Filenames carry the capture's 8-character URL hash. The note can afford a
title-derived name because it has a manifest behind it and collisions are
detected and repaired; the portable copy is a derived artifact and the hash is
what makes re-saving the same URL an idempotent overwrite rather than a second
file. It also keeps the two apart in a directory listing: `Decorators.md` is
yours to edit, `Decorators-a1b2c3d4.html` is rebuilt from the archive whenever
the page is captured again.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .capture.compile import CompileError, compile_html
from .capture.paths import safe_filename


@dataclass
class MirrorResult:
    page: Path | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.page is not None


def capture_digest(capture_dir: Path) -> str:
    """The stable URL hash the capture directory is named with."""
    return capture_dir.name.rsplit("-", 1)[-1]


def mirror_name(title: str, capture_dir: Path) -> str:
    return f"{safe_filename(title)}-{capture_digest(capture_dir)}"


def mirror_capture(*, capture_dir: Path, note_path: Path, title: str) -> MirrorResult:
    """Build the self-contained page beside its note.

    Never fatal. A failure here means one convenience copy is missing, which
    should not take down the save that already succeeded -- so the error is
    returned for reporting rather than raised. A capture with no page.html (a
    plain .txt upload, say) simply has no portable copy to build.
    """
    target_dir = note_path.parent
    stem = mirror_name(title, capture_dir)
    try:
        return MirrorResult(page=compile_html(capture_dir, target_dir / f"{stem}.html"))
    except (CompileError, OSError) as exc:
        return MirrorResult(error=f"note saved, portable copy not built: {exc}")


def prune_stale(*, title: str, capture_dir: Path, note_path: Path) -> None:
    """Remove a portable copy left behind when a page changes title.

    The hash keeps the *new* name stable and collision-free, but a retitled
    page still leaves its old name sitting there. The digest is what identifies
    the file as belonging to this capture, so anything sharing the digest and
    not matching the current name is a leftover.
    """
    target_dir = note_path.parent
    if not target_dir.is_dir():
        return
    digest = capture_digest(capture_dir)
    keep = mirror_name(title, capture_dir)
    for path in target_dir.glob(f"*-{digest}.html"):
        if path.stem != keep:
            try:
                path.unlink()
            except OSError:
                pass
