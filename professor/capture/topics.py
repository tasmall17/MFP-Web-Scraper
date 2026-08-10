"""The topic funnel: decide which directory a capture belongs in.

The problem this solves, in the user's words: "what if it's another page on
python and I already have a py-professor dir with 3 things in it? I wouldn't
want it to make a new directory, I would want it to add it to the py-professor
dir."

The shape is **normalize -> dictionary lookup -> slow path only on a miss**:

    "-python"  ->  normalize -> "python"  ->  dict hit?  -> yes: done, O(1)
                                                         -> no:  fuzzy scan,
                                                                 then WRITE THE
                                                                 RESULT BACK

That write-back matters. An expensive fuzzy match runs once per new alias
*ever*; every future `-python` is a plain dictionary hit. Same idea as
memoization -- caching the answer to "what did I mean by this word?"

Two details make the fuzzy match actually work, and both were found by testing
rather than guessing:

1. **Compare stems.** Strip the "-professor" suffix from both sides first.
   Otherwise every directory shares 10 characters of suffix, which dominates
   the similarity ratio -- inflating unrelated pairs while doing nothing for
   related ones.

2. **Match prefixes in both directions.** The naive rule "slug is a prefix of
   an existing topic" is one-directional and misses the exact scenario above:
   with `py-professor` on disk and `-python` typed, `python` is not a prefix of
   `py`, and difflib scores the pair 0.333 -- under any sane threshold. So it
   would create the duplicate. Checking *either* direction fixes it.

Disk is authoritative; topics.json is a rebuildable cache. The user will create
and rename directories by hand, so a registry that can't be regenerated from a
directory listing will drift out of sync with reality.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .paths import (
    INBOX_TOPIC,
    MACHINE_DIR,
    RESERVED_DIRNAMES,
    TOPIC_SUFFIX,
    ensure_library,
    ensure_topic_layout,
    slugify,
    topics_file,
)

# Similarity at or above this binds an alias to an existing topic.
FUZZY_THRESHOLD = 0.72
# Prefix matching below this length is too trigger-happy to trust.
MIN_PREFIX_LEN = 2


@dataclass
class Resolution:
    """What the funnel decided, and why -- so the CLI can explain itself."""

    directory: Path
    alias: str
    action: str  # "exact" | "bound" | "created"
    matched_topic: str | None = None
    score: float | None = None

    @property
    def is_new_directory(self) -> bool:
        return self.action == "created"


def stem(name: str) -> str:
    """'python-professor' -> 'python'.  '-py' -> 'py'."""
    s = name.strip().lower().lstrip("-")
    if s.endswith(TOPIC_SUFFIX):
        s = s[: -len(TOPIC_SUFFIX)]
    return s.strip("-")


def normalize_alias(raw: str) -> str:
    """Turn a raw CLI token like '--Py3' into the dictionary key 'py3'."""
    return slugify(stem(raw))


def dir_name_for(alias: str) -> str:
    """The directory a brand-new topic gets: 'py' -> 'py-professor'.

    'inbox' is the one exception. It is where untagged captures land, not a
    subject, and 'inbox-professor' reads like nonsense.
    """
    base = slugify(stem(alias))
    if base == INBOX_TOPIC:
        return INBOX_TOPIC
    return f"{base}{TOPIC_SUFFIX}"


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def matches(a: str, b: str) -> tuple[bool, float]:
    """Do two stems refer to the same topic?

    Returns (matched, score). Prefix hits report their ratio for display but
    bind regardless of it -- 'py' vs 'python' only scores 0.5, which is why
    the ratio alone is not enough.
    """
    if not a or not b:
        return False, 0.0
    score = similarity(a, b)
    if a == b:
        return True, 1.0
    if len(a) >= MIN_PREFIX_LEN and b.startswith(a):
        return True, score
    if len(b) >= MIN_PREFIX_LEN and a.startswith(b):
        return True, score
    return score >= FUZZY_THRESHOLD, score


class TopicRegistry:
    """The alias dictionary, backed by .mfp/topics.json."""

    def __init__(self, root: Path | None = None):
        self.root = ensure_library(root)
        self.path = topics_file(self.root)
        self._aliases: dict[str, str] = {}
        self._load()

    # ---------------------------------------------------------------- storage

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._aliases = dict(data.get("aliases", {}))
            except (json.JSONDecodeError, OSError):
                # A corrupt cache is not a crash -- disk is authoritative and
                # we can rebuild the whole thing from a directory listing.
                self._aliases = {}
        self._prune_missing()
        self._absorb_disk()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_comment": (
                "Rebuildable cache of alias -> topic directory. Disk is "
                "authoritative; delete this file and it regenerates."
            ),
            "aliases": dict(sorted(self._aliases.items())),
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------ disk

    def topic_dirs(self) -> list[Path]:
        """Visible topic directories on disk, which are the real source of truth.

        RESERVED_DIRNAMES is excluded here rather than at the call sites because
        _absorb_disk() runs on every load and would otherwise mint an alias for
        anything sitting beside the topics -- silently turning the learning
        profile into a subject you could capture pages into.
        """
        if not self.root.exists():
            return []
        return sorted(
            p
            for p in self.root.iterdir()
            if p.is_dir()
            and not p.name.startswith(".")
            and p.name != MACHINE_DIR
            and p.name not in RESERVED_DIRNAMES
        )

    def _prune_missing(self) -> None:
        """Drop aliases pointing at directories the user deleted or renamed."""
        for alias, name in list(self._aliases.items()):
            if not (self.root / name).is_dir():
                del self._aliases[alias]

    def _absorb_disk(self) -> None:
        """Every topic directory answers to its own stem, for free."""
        for d in self.topic_dirs():
            self._aliases.setdefault(stem(d.name), d.name)

    # ------------------------------------------------------------- resolution

    def resolve(self, raw_alias: str, *, force_new: bool = False) -> Resolution:
        """Map a CLI topic flag to a directory, creating or binding as needed."""
        alias = normalize_alias(raw_alias)
        if not alias:
            raise ValueError("empty topic alias")

        # 1. Exact hit -- the fast path, and after the first use of any alias
        #    this is the only path that ever runs.
        if not force_new and alias in self._aliases:
            directory = self.root / self._aliases[alias]
            if directory.is_dir():
                return Resolution(directory, alias, "exact")

        # 2. Miss -> fuzzy scan against what is actually on disk.
        if not force_new:
            best = self._best_match(alias)
            if best is not None:
                directory, score = best
                self._aliases[alias] = directory.name
                self.save()
                return Resolution(
                    directory, alias, "bound",
                    matched_topic=directory.name, score=score,
                )

        # 3. No match -> a genuinely new topic.
        directory = ensure_topic_layout(self.root / dir_name_for(alias))
        self._aliases[alias] = directory.name
        self.save()
        return Resolution(directory, alias, "created")

    def _best_match(self, alias: str) -> tuple[Path, float] | None:
        """Highest-scoring existing topic that matches, if any."""
        target = stem(alias)
        best: tuple[Path, float] | None = None
        for directory in self.topic_dirs():
            # Compare against the directory's own stem and every alias already
            # bound to it, so '-py3' can find a dir reached earlier via '-py'.
            candidates = {stem(directory.name)}
            candidates.update(
                a for a, name in self._aliases.items() if name == directory.name
            )
            for candidate in candidates:
                ok, score = matches(target, stem(candidate))
                if ok and (best is None or score > best[1]):
                    best = (directory, score)
        return best

    # ------------------------------------------------------------ maintenance

    def link(self, alias: str, topic_dir_name: str) -> Path:
        """Bind an alias by hand -- the fix for any bad automatic guess."""
        alias = normalize_alias(alias)
        directory = self.root / topic_dir_name
        if not directory.is_dir():
            # Accept a bare stem too: `--link ml=machine-learning` should work.
            alt = self.root / dir_name_for(topic_dir_name)
            if alt.is_dir():
                directory = alt
            else:
                raise FileNotFoundError(f"no such topic directory: {topic_dir_name}")
        self._aliases[alias] = directory.name
        self.save()
        return directory

    def rebuild(self) -> None:
        """Resynchronise the cache with what is actually on disk.

        Hand-made links are kept as long as their target directory still
        exists. A rebuild that discarded them would quietly undo every
        `--link ml=machine-learning-professor` the user ever made -- and those
        are exactly the bindings the fuzzy matcher can't rediscover on its own,
        since string similarity doesn't do synonyms.
        """
        self._aliases = {
            alias: name
            for alias, name in self._aliases.items()
            if (self.root / name).is_dir()
        }
        self._absorb_disk()
        self.save()

    def summary(self) -> list[tuple[str, list[str], int]]:
        """(directory, aliases, capture count) for `--topics`."""
        rows = []
        for directory in self.topic_dirs():
            aliases = sorted(
                a for a, name in self._aliases.items() if name == directory.name
            )
            captures = directory / CAPTURES_DIR
            count = len([p for p in captures.iterdir() if p.is_dir()]) if captures.is_dir() else 0
            rows.append((directory.name, aliases, count))
        return rows
