"""The audit log and the failed-attempts CSV.

Both live in the hidden .mfp/ directory. Timestamps are date + 24-hour time
with **no seconds**, deliberately: the audit log is the last-ditch record, and
its job is to give you a timestamp you can carry over to your browser history
to find a page by hand. Seconds don't help with that and just add noise.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .paths import audit_file, ensure_library, failures_file

TIME_FMT = "%Y-%m-%d %H:%M"

CSV_HEADER = ["failed_at", "topic", "domain", "url", "stage", "reason"]

# Width of the action column, so entries line up when you read the log.
_ACTION_W = 7


def now_stamp() -> str:
    return datetime.now().strftime(TIME_FMT)


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.removeprefix("www.") or "?"
    except Exception:
        return "?"


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")


def audit(action: str, message: str, *, root: Path | None = None,
          continuation: str = "") -> None:
    """Write one audit line (plus an optional indented continuation line)."""
    root = ensure_library(root)
    stamp = now_stamp()
    line = f"{stamp}  {action.upper():<{_ACTION_W}} {message}"
    if continuation:
        pad = " " * (len(stamp) + 2 + _ACTION_W + 1)
        line += f"\n{pad}{continuation}"
    _append(audit_file(root), line)


def audit_create(topic_dir: Path, alias: str, *, root: Path | None = None) -> None:
    audit("CREATE", f"{topic_dir.name}/  (from alias {alias!r})", root=root)


def audit_link(alias: str, topic_dir: Path, *, root: Path | None = None) -> None:
    audit("LINK", f"alias {alias!r} -> existing {topic_dir.name}/", root=root)


def audit_saved(url: str, note_path: Path, tier: str, *, updated: bool = False,
                root: Path | None = None) -> None:
    """Record a successful capture. UPDATE when it replaced a prior one."""
    root = ensure_library(root)
    rel = _relative_to_library(note_path, root)
    audit(
        "UPDATE" if updated else "SAVED",
        url,
        continuation=f"-> {rel}  [{tier}]",
        root=root,
    )


def audit_fail(url: str, reason: str, stage: str, *, root: Path | None = None) -> None:
    audit(
        "FAIL",
        url,
        continuation=f"{stage}: {reason} -> wrote .mfp/failed-attempts.csv",
        root=root,
    )


def _relative_to_library(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def record_failure(url: str, topic: str, stage: str, reason: str,
                   *, root: Path | None = None) -> Path:
    """Append one row to failed-attempts.csv and mirror it into the audit log.

    Only *total* failures land here -- the page was unreachable, or no article
    content could be extracted. Losing some images still counts as a success,
    otherwise a page that dropped two tracking pixels would sit in the retry
    queue forever.
    """
    root = ensure_library(root)
    path = failures_file(root)
    is_new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(CSV_HEADER)
        writer.writerow([
            now_stamp(),
            topic,
            domain_of(url),
            url,
            stage,
            # Collapse newlines so one failure is always exactly one row.
            " ".join(str(reason).split()),
        ])
    audit_fail(url, reason, stage, root=root)
    return path


def read_failures(root: Path | None = None) -> list[dict[str, str]]:
    path = failures_file(root or ensure_library(root))
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def rewrite_failures(rows: list[dict[str, str]], root: Path | None = None) -> None:
    """Replace the CSV wholesale -- used by --retry-failed to drop fixed rows."""
    path = failures_file(root or ensure_library(root))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_HEADER})
