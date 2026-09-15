"""Where everything lives.

One rule drives this module: the user sees exactly one Markdown file per
capture, sitting in a lecture folder. Every other artifact -- the alias
dictionary, the audit log, the failure CSV, the archived HTML and its images --
is machinery, and machinery is hidden.

The library is **the directory you run `mfp` in**. There is no fixed home for
it: captures land beside you, in the project you are working on, and moving the
material is a `mv` rather than a setting. MFP_LIBRARY (or --library) overrides
that when you want one collection regardless of where you stand.

    $PWD/
      .mfp/                     alias dictionary, audit log, failure CSV
      py-University/            a topic
        py-Lecture/             its own lecture: notes for a bare `-py`
          Primer on Decorators.md
          Primer on Decorators-a1b2c3d4.html    self-contained, opens anywhere
        async-Lecture/          from `mfp -py.async <url>`
        .captures/              one archive per university, shared by lectures
          realpython-decorators-a1b2c3d4/
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# The two visible suffixes. Capitalised because they are read, not typed: the
# alias you type is always the bare stem, and the funnel lowercases it.
UNIVERSITY_SUFFIX = "-University"
LECTURE_SUFFIX = "-Lecture"

# The single hidden directory holding all cross-topic machinery.
MACHINE_DIR = ".mfp"
# Hidden directory inside each university holding the archived pages. It sits
# at university level rather than inside a lecture so that every lecture shares
# one archive, and so find_capture() stays a single-level glob.
CAPTURES_DIR = ".captures"

INBOX_TOPIC = "inbox"

# What is structure rather than a lecture, inside a university. Both are
# dot-prefixed and so are already filtered out by the rule that hides them
# everywhere else; they are named here so this set answers "what is structure?"
# rather than "what does the current filter happen to miss?".
TOPIC_STRUCTURE_DIRNAMES = frozenset({CAPTURES_DIR, MACHINE_DIR})


def library_root() -> Path:
    """The library directory: where you are, unless MFP_LIBRARY says otherwise."""
    env = os.environ.get("MFP_LIBRARY", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.cwd()


def machine_dir(root: Path | None = None) -> Path:
    return (root or library_root()) / MACHINE_DIR


def topics_file(root: Path | None = None) -> Path:
    return machine_dir(root) / "topics.json"


def audit_file(root: Path | None = None) -> Path:
    return machine_dir(root) / "audit.log"


def failures_file(root: Path | None = None) -> Path:
    return machine_dir(root) / "failed-attempts.csv"


def is_university(path: Path) -> bool:
    return path.name.lower().endswith(UNIVERSITY_SUFFIX.lower())


def is_lecture(path: Path) -> bool:
    return path.name.lower().endswith(LECTURE_SUFFIX.lower())


def university_of(lecture_dir: Path) -> Path:
    """The university a lecture belongs to.

    Derived rather than passed around, because the resolver guarantees the
    invariant it rests on: a lecture directory always sits *directly* inside
    its university. That is the same relationship find_capture() walks when it
    is handed a note and has to find the archive behind it.
    """
    return lecture_dir.parent


def captures_dir(university_dir: Path) -> Path:
    """The archive directory, which belongs to a university, not a lecture."""
    return university_dir / CAPTURES_DIR


def captures_dir_for_lecture(lecture_dir: Path) -> Path:
    return captures_dir(university_of(lecture_dir))


def ensure_university(university_dir: Path) -> Path:
    """Create a university and its archive directory. Safe to call repeatedly."""
    university_dir.mkdir(parents=True, exist_ok=True)
    captures_dir(university_dir).mkdir(exist_ok=True)
    return university_dir


def ensure_lecture(lecture_dir: Path) -> Path:
    """Create a lecture, and the university above it if it isn't there yet."""
    ensure_university(university_of(lecture_dir))
    lecture_dir.mkdir(exist_ok=True)
    return lecture_dir


def ensure_library(root: Path | None = None) -> Path:
    """Create the library and its hidden machine directory if absent."""
    root = root or library_root()
    root.mkdir(parents=True, exist_ok=True)
    machine_dir(root).mkdir(exist_ok=True)
    return root


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    """Lowercase, hyphen-joined, filesystem-safe."""
    s = _SLUG_STRIP.sub("-", (text or "").strip().lower()).strip("-")
    return s[:max_len].strip("-") or "untitled"


_UNSAFE_FILENAME = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def safe_filename(title: str, max_len: int = 120) -> str:
    """A human-readable filename that won't upset the filesystem.

    Unlike slugify this keeps spaces and capitalisation -- these become the
    note titles the user actually reads, so 'Primer on Python Decorators.md'
    beats 'primer-on-python-decorators.md'.
    """
    name = _UNSAFE_FILENAME.sub("-", (title or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .-")
    if len(name) > max_len:
        name = name[:max_len].rsplit(" ", 1)[0].strip()
    return name or "Untitled"
