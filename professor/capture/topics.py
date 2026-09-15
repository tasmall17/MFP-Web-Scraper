"""The topic funnel: decide which directory a capture belongs in.

The problem this solves, in the user's words: "what if it's another page on
python and I already have a py-University dir with 3 things in it? I wouldn't
want it to make a new directory, I would want it to add it to the py-University
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

1. **Compare stems.** Strip the "-University"/"-Lecture" suffix from both sides
   first. Otherwise every directory shares 10 characters of suffix, which
   dominates the similarity ratio -- inflating unrelated pairs while doing
   nothing for related ones.

2. **Match prefixes in both directions.** The naive rule "slug is a prefix of
   an existing topic" is one-directional and misses the exact scenario above:
   with `py-University` on disk and `-python` typed, `python` is not a prefix of
   `py`, and difflib scores the pair 0.333 -- under any sane threshold. So it
   would create the duplicate. Checking *either* direction fixes it.

Every capture lands in a lecture, so the funnel always runs twice: once to pick
the university, once to pick the lecture inside it. A bare `-py` is simply the
case where both levels are asked the same question, which is why it lands in
`py-University/py-Lecture/` rather than loose in the university directory.

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
    CAPTURES_DIR,
    INBOX_TOPIC,
    LECTURE_SUFFIX,
    UNIVERSITY_SUFFIX,
    ensure_lecture,
    ensure_library,
    ensure_university,
    is_lecture,
    is_university,
    slugify,
    topics_file,
)

# Similarity at or above this binds an alias to an existing topic.
FUZZY_THRESHOLD = 0.72
# Prefix matching below this length is too trigger-happy to trust. Note this
# constrains the *prefix*, never the alias: '-ltt' and '-rei' are ordinary
# three-character aliases and always have been.
MIN_PREFIX_LEN = 2

# Separates a university from a lecture in a CLI flag: `-js.react`.
SUBTOPIC_SEP = "."


@dataclass
class Resolution:
    """What the funnel decided, and why -- so the CLI can explain itself.

    `directory` is always the **lecture**: the directory the note actually
    lands in. The university's own outcome rides along in `university` and
    `university_action` so a first `-js.react` on an empty library can report
    both directories it created rather than silently making one of them.
    """

    directory: Path
    alias: str
    action: str  # "exact" | "bound" | "created"
    university: Path
    university_action: str
    matched_topic: str | None = None
    score: float | None = None

    @property
    def is_new_directory(self) -> bool:
        return self.action == "created"

    @property
    def flag(self) -> str:
        """The shortest flag that reaches this lecture again.

        The dictionary key for a bare `-py` is 'py.py' -- the same question
        asked at both levels -- which is correct storage and terrible advice to
        print back at someone. When the lecture is its university's namesake,
        the flag that gets you there is just '-py'.
        """
        head, _, tail = self.alias.partition(SUBTOPIC_SEP)
        return head if head == tail or not tail else self.alias

    @property
    def label(self) -> str:
        """The capture's identity everywhere outside the filesystem.

        'js-University/js-Lecture'. This is what goes in the manifest and the
        note id: two lectures under one university can hold notes with the same
        filename, and a bare lecture name would not tell them apart.
        """
        return f"{self.university.name}/{self.directory.name}"


def stem(name: str) -> str:
    """'python-University' -> 'python'.  '-py' -> 'py'.  'py-Lecture' -> 'py'."""
    s = name.strip().lower().lstrip("-")
    for suffix in (UNIVERSITY_SUFFIX.lower(), LECTURE_SUFFIX.lower()):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.strip("-")


def normalize_alias(raw: str) -> str:
    """Turn a raw CLI token like '--Py3' into the dictionary key 'py3'."""
    return slugify(stem(raw))


def split_alias(raw: str) -> tuple[str, str | None]:
    """'-js.react' -> ('js', 'react').  '-js' -> ('js', None).

    This has to run *before* normalize_alias(), and that ordering is the whole
    reason it is a separate function: slugify() rewrites '.' to '-', so a
    dotted token handed to it whole comes back as the single name 'js-react' --
    a plausible-looking directory that is not what anyone asked for and gives
    no hint that nesting was ever attempted.

    Nesting stops at one level. A second dot joins into the lecture name
    ('-js.react.hooks' -> 'react-hooks-Lecture') rather than inventing a
    grandchild, because the layout has exactly two levels and a third would put
    captures somewhere find_capture() cannot see them.
    """
    token = raw.strip().lstrip("-")
    head, sep, tail = token.partition(SUBTOPIC_SEP)
    if not sep:
        return token, None
    tail = tail.replace(SUBTOPIC_SEP, "-").strip("-")
    return head, (tail or None)


def normalize_key(raw: str) -> str:
    """The dictionary key for a raw flag, dot intact: '-JS.React' -> 'js.react'."""
    head, tail = split_alias(raw)
    head = normalize_alias(head)
    if tail is None:
        return head
    return f"{head}{SUBTOPIC_SEP}{normalize_alias(tail)}"


def dir_name_for(alias: str) -> str:
    """The directory a brand-new university gets: 'py' -> 'py-University'."""
    return f"{slugify(stem(alias)) or INBOX_TOPIC}{UNIVERSITY_SUFFIX}"


def lecture_dir_name_for(alias: str) -> str:
    """The directory a brand-new lecture gets: 'react' -> 'react-Lecture'."""
    return f"{slugify(stem(alias)) or INBOX_TOPIC}{LECTURE_SUFFIX}"


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
    """The alias dictionary, backed by .mfp/topics.json.

    Two kinds of key live in one flat dictionary, told apart by the dot:

        "py"        -> "py-University"                 a university
        "py.async"  -> "py-University/async-Lecture"   a lecture inside it
        "py.py"     -> "py-University/py-Lecture"      the bare `-py` lecture

    The third is not a special case: `mfp -py` asks the same question at both
    levels, so it writes the same answer at both levels.
    """

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
                "Rebuildable cache of alias -> directory. A bare key names a "
                "university, a dotted key names a lecture inside one. Disk is "
                "authoritative; delete this file and it regenerates."
            ),
            "aliases": dict(sorted(self._aliases.items())),
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------ disk

    def topic_dirs(self) -> list[Path]:
        """The university directories, which are the real source of truth.

        Identified by their suffix rather than by "every visible directory",
        because the library is now whatever directory you ran `mfp` in. That
        directory belongs to you: it may hold a src/, a docs/ and a build/, and
        adopting those as subjects -- writing an alias for each, then offering
        to capture into them -- would be the funnel helping itself to a project
        it was only visiting.
        """
        if not self.root.exists():
            return []
        return sorted(
            p
            for p in self.root.iterdir()
            if p.is_dir() and not p.name.startswith(".") and is_university(p)
        )

    def lecture_dirs(self, university_dir: Path) -> list[Path]:
        """The lecture directories inside one university.

        Same suffix rule, for the same reason plus one more: `mkdir
        js-University/hooks-Lecture` works exactly as well as `mfp -n js.hooks`,
        which is the "disk is authoritative" rule holding at both levels.
        """
        if not university_dir.is_dir():
            return []
        return sorted(
            p
            for p in university_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".") and is_lecture(p)
        )

    def _rel(self, directory: Path) -> str:
        """The stored form: 'js-University', or 'js-University/react-Lecture'."""
        return directory.relative_to(self.root).as_posix()

    def _prune_missing(self) -> None:
        """Drop aliases pointing at directories the user deleted or renamed."""
        for alias, name in list(self._aliases.items()):
            if not (self.root / name).is_dir():
                del self._aliases[alias]

    def _absorb_disk(self) -> None:
        """Every university and lecture answers to its own stem, for free."""
        for university in self.topic_dirs():
            self._aliases.setdefault(stem(university.name), university.name)
            for lecture in self.lecture_dirs(university):
                key = f"{stem(university.name)}{SUBTOPIC_SEP}{stem(lecture.name)}"
                self._aliases.setdefault(key, self._rel(lecture))

    # ------------------------------------------------------------- resolution

    def resolve(self, raw_alias: str, *, force_new: bool = False) -> Resolution:
        """Map a CLI topic flag to the lecture directory a capture lands in.

        `-js` and `-js.react` differ only in what the second level is asked:
        the bare form asks for a lecture named after the university itself.
        Both levels run the same funnel, so everything true of universities is
        true of lectures: '-js.rea' finds an existing react-Lecture/, the
        binding is written back, and only a genuine miss creates a directory.
        """
        head, tail = split_alias(raw_alias)

        # force_new is deliberately NOT passed to the university. On a dotted
        # flag it means "a separate lecture", and forcing the university as
        # well would answer `--new-topic -python.async`, with py-University
        # already on disk, by creating a second python-University/ to hold it --
        # the exact duplicate the funnel exists to prevent, in the one command
        # whose whole purpose is to be deliberate about creating a directory.
        university, uni_action, uni_matched, uni_score = self._resolve_university(
            head, force_new=force_new and tail is None
        )
        return self._resolve_lecture(
            university, uni_action, tail if tail is not None else head,
            force_new=force_new,
            uni_matched=uni_matched, uni_score=uni_score,
        )

    def _resolve_university(self, raw_alias: str, *, force_new: bool = False
                            ) -> tuple[Path, str, str | None, float | None]:
        alias = normalize_alias(raw_alias)
        if not alias:
            raise ValueError("empty topic alias")

        # 1. Exact hit -- the fast path, and after the first use of any alias
        #    this is the only path that ever runs.
        if not force_new and alias in self._aliases:
            directory = self.root / self._aliases[alias]
            if directory.is_dir() and is_university(directory):
                return directory, "exact", None, None

        # 2. Miss -> fuzzy scan against what is actually on disk.
        if not force_new:
            best = self._best_match(alias, self.topic_dirs())
            if best is not None:
                directory, score = best
                self._aliases[alias] = self._rel(directory)
                self.save()
                return directory, "bound", directory.name, score

        # 3. No match -> a genuinely new university.
        directory = ensure_university(self.root / dir_name_for(alias))
        self._aliases[alias] = self._rel(directory)
        self.save()
        return directory, "created", None, None

    def _resolve_lecture(self, university: Path, university_action: str,
                         raw_lecture: str, *, force_new: bool = False,
                         uni_matched: str | None = None,
                         uni_score: float | None = None) -> Resolution:
        """Second level of the funnel, inside an already-resolved university."""
        lecture_alias = normalize_alias(raw_lecture)
        if not lecture_alias:
            raise ValueError("empty lecture alias")
        key = f"{normalize_alias(stem(university.name))}{SUBTOPIC_SEP}{lecture_alias}"

        def resolved(directory: Path, action: str, **extra) -> Resolution:
            return Resolution(
                directory, key, action,
                university=university, university_action=university_action,
                **extra,
            )

        if not force_new and key in self._aliases:
            directory = self.root / self._aliases[key]
            if directory.is_dir():
                return resolved(directory, "exact",
                                matched_topic=uni_matched, score=uni_score)

        if not force_new:
            best = self._best_match(lecture_alias, self.lecture_dirs(university))
            if best is not None:
                directory, score = best
                self._aliases[key] = self._rel(directory)
                self.save()
                return resolved(directory, "bound",
                                matched_topic=directory.name, score=score)

        directory = ensure_lecture(university / lecture_dir_name_for(lecture_alias))
        self._aliases[key] = self._rel(directory)
        self.save()
        return resolved(directory, "created")

    def _best_match(self, alias: str,
                    directories: list[Path]) -> tuple[Path, float] | None:
        """Highest-scoring directory in `directories` that matches, if any.

        Takes its candidates as an argument rather than reading topic_dirs()
        itself, which is what lets the identical rule serve both levels: the
        lecture pass simply hands it one university's children.
        """
        target = stem(alias)
        best: tuple[Path, float] | None = None
        for directory in directories:
            rel = self._rel(directory)
            # Compare against the directory's own stem and every alias already
            # bound to it, so '-py3' can find a dir reached earlier via '-py'.
            # A lecture alias is stored dotted ('js.react'), and only its last
            # segment names this directory -- comparing the whole key would
            # score the university's name as part of the lecture's.
            candidates = {stem(directory.name)}
            candidates.update(
                a.rpartition(SUBTOPIC_SEP)[2] or a
                for a, name in self._aliases.items() if name == rel
            )
            for candidate in candidates:
                ok, score = matches(target, stem(candidate))
                if ok and (best is None or score > best[1]):
                    best = (directory, score)
        return best

    # ------------------------------------------------------------ maintenance

    def link(self, alias: str, target_name: str) -> Path:
        """Bind an alias by hand -- the fix for any bad automatic guess.

        Both sides accept the dotted form, so a lecture can be linked the same
        way a university can: `--link hooks=js-University/react-Lecture`, or
        `--link js.hooks=js-University/react-Lecture`.
        """
        alias = normalize_key(alias)
        target = target_name.strip().strip("/")
        directory = self.root / target
        if not directory.is_dir():
            # Accept bare stems too: `--link ml=machine-learning` should work,
            # and so should `--link ml=machine-learning/intro`.
            head, _, tail = target.partition("/")
            alt = self.root / dir_name_for(head)
            if tail:
                alt = alt / lecture_dir_name_for(tail)
            if alt.is_dir():
                directory = alt
            else:
                raise FileNotFoundError(f"no such directory: {target_name}")
        self._aliases[alias] = self._rel(directory)
        self.save()
        return directory

    def rebuild(self) -> None:
        """Resynchronise the cache with what is actually on disk.

        Hand-made links are kept as long as their target directory still
        exists. A rebuild that discarded them would quietly undo every
        `--link ml=machine-learning-University` the user ever made -- and those
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

    def summary(self) -> list[tuple[str, list[str], int, int]]:
        """(name, aliases, item count, depth) for `--topics`.

        Lectures follow their university, at depth 1, so the listing reads in
        the same shape as the directory tree it describes. The count is
        archived captures for a university and notes for a lecture -- the thing
        you would actually find if you opened that directory.
        """
        rows: list[tuple[str, list[str], int, int]] = []
        for university in self.topic_dirs():
            captures = university / CAPTURES_DIR
            count = (
                len([p for p in captures.iterdir() if p.is_dir()])
                if captures.is_dir() else 0
            )
            rows.append((university.name, self._aliases_for(university), count, 0))
            for lecture in self.lecture_dirs(university):
                notes = len(list(lecture.glob("*.md")))
                rows.append((lecture.name, self._aliases_for(lecture), notes, 1))
        return rows

    def _aliases_for(self, directory: Path) -> list[str]:
        rel = self._rel(directory)
        return sorted(a for a, name in self._aliases.items() if name == rel)
