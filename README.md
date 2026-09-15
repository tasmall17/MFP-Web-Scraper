# MFP-Web-Scraper

Save a web page as something you can actually read later.

Point it at a URL and you get two things: a clean Markdown note with the
navigation, ads and cookie banners stripped out, and a hidden archive holding
the page with every image inlined — so it still works offline, on a plane,
years from now.

It also walks GitHub trees and crawls whole documentation sections.

No account, no server, nothing to configure. It runs, it writes files, it exits.

---

## Install

macOS or Linux, zsh or bash.

```sh
git clone https://github.com/tasmall17/MFP-Web-Scraper.git
cd MFP-Web-Scraper
./install.sh
```

That's it. The script installs [uv](https://astral.sh/uv) if you don't have
it, fetches Python 3.12 and the dependencies, puts `mfp` on your `PATH`, and
downloads the Chromium build used for pages that need JavaScript.

If it had to add `~/.local/bin` to your `PATH`, open a new terminal
afterwards — it will tell you when that happens.

```sh
mfp --self-test      # check the fetch ladder end to end
```

Pass `--no-browser` to skip the ~400MB Chromium download. Everything still
works except pages that need JavaScript to render.

---

## Use

Captures land **in the directory you run it from**, so `cd` to wherever you
want the material first.

```sh
mfp -py https://realpython.com/primer-on-python-decorators/
```

`-py` is a **topic**, invented on the spot. It creates `py-University/` and
files the note in `py-University/py-Lecture/`. Typing `-python` later lands in
the same place rather than making a second directory — `-py`, `-pyt` and
`-python` all reach it.

A dot picks a different lecture under the same university:

```sh
mfp -py.async https://docs.python.org/3/library/asyncio.html
```

That one files into `py-University/async-Lecture/`. The university is the
subject; a lecture is one strand of it.

### Crawl a whole site section

```sh
mfp -py --full https://docs.example.com/guide/
```

Follows every same-site link from that page, capturing each one it finds into
a lecture of its own — `guide-Lecture/`, named after the page you started
from. It stops when the site runs out of new links or when `--max-pages`
(default 200) is hit. Links to other domains are never followed. `--depth N`
stops after N hops instead.

### Walk a GitHub repository

```sh
mfp -py --repo owner/repo
mfp -py https://github.com/owner/repo/tree/main/docs
```

Every text file under that point becomes one Markdown note: a directory tree,
a table of contents, then each file in path order. Code is fenced with its
language. Dependencies, build output, lockfiles, minified bundles and binaries
are skipped. Narrow it with `--only` and `--skip` globs, raise the ceiling with
`--max-bytes`, or force `--page` to scrape the GitHub page as an ordinary page.

**Full option reference:** [`man-mfp.md`](man-mfp.md) — a proper `mfp(1)` man
page, also readable offline with `mfp --man`.

---

## Where files land

Everything goes under the directory you ran `mfp` in:

```
./
  .mfp/                             the alias dictionary and logs
  py-University/
    py-Lecture/                     where a bare -py lands
      Primer on Python Decorators.md            the note you read
      Primer on Python Decorators-a1b2c3d4.html self-contained, opens anywhere
    async-Lecture/                  from -py.async
    .captures/                      the archives, images and all
      realpython-decorators-a1b2c3d4/
```

Two files per capture, side by side. The Markdown note is yours to read and
edit; the `.html` beside it has every image inlined, so you can double-click
it, mail it to someone, or open it offline in ten years with none of this
installed. Its filename carries a content hash, so re-saving a page overwrites
cleanly and two pages sharing a title can't clobber each other.

One `.captures/` serves every lecture in a university. It holds the raw
archive each note was built from, which is what makes `--compile` work offline
and lets a page be re-extracted without fetching it again.

Set `MFP_LIBRARY` (or pass `--library PATH`) to capture somewhere other than
the current directory.

### The alias dictionary

`.mfp/topics.json` is a dictionary of the shorthand you type to the directory
it means:

```json
{
  "aliases": {
    "py":       "py-University",
    "py.py":    "py-University/py-Lecture",
    "py.async": "py-University/async-Lecture"
  }
}
```

It exists so `-py`, `-pyt` and `-python` keep landing in the same place. The
first time you type a new alias, the tool compares it against the directories
actually on disk — matching prefixes in either direction, so `-python` finds an
existing `py-University/` — and **writes the answer back**. Every later use is
a plain dictionary lookup rather than a fresh guess.

A bare key names a university, a dotted key names a lecture inside one.
`"py.py"` is not a special case: `mfp -py` asks the same question at both
levels, so it records the same answer at both levels.

The file is a cache, not the truth. Disk is the truth — you can rename or
delete directories by hand, and `mfp --rebuild` regenerates the dictionary from
what is actually there. Delete the file entirely and it comes back. Two
commands to inspect and correct it:

```sh
mfp --topics                          # every university, lecture and alias
mfp --link ml=machine-learning        # bind an alias the matcher got wrong
```

Hand-made `--link` bindings survive a rebuild, because string similarity can't
rediscover a synonym.

---

## How it fetches

Four tiers, escalating only as needed — most pages never leave the first:

| | |
|---|---|
| **T1** | plain HTTP via `httpx` |
| **T2** | headless Chromium, for pages that need JavaScript |
| **T3** | a stealth browser profile, for pages that block T2 |
| **T4** | archive fallback |

`--no-t3` stops after T2, which makes a failure fail faster.

---

## Related

This is the capture half of
[my-favorite-professor](https://github.com/tasmall17/my-favorite-professor),
packaged on its own. That project adds a local web app that turns the material
into a course with a Claude alongside it; this one is just the scraper.

## Licence

MIT.
