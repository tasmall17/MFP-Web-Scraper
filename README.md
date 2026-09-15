# MFP-Web-Scraper

Save a web page as something you can actually read later.

Point it at a URL and you get two things: a clean Markdown note with the
navigation, ads and cookie banners stripped out, and a hidden archive holding
the page with every image inlined — so it still works offline, on a plane,
years from now.

It also walks GitHub trees and crawls whole documentation sections.

No account, no API key, no server. It runs, it writes files, it exits.

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

```sh
mfp -py https://realpython.com/primer-on-python-decorators/
```

`-py` is a **topic**, invented on the spot. It files the note under
`py-professor/`. Typing `-python` later lands in the same place rather than
making a second directory — `-py`, `-pyt` and `-python` all reach it.

A dot nests one level, for a subject that belongs under one you already have:

```sh
mfp -py.async https://docs.python.org/3/library/asyncio.html
```

### Crawl a whole site section

```sh
mfp -py --full https://docs.example.com/guide/
```

Follows every same-site link from that page, capturing each one it finds. It
stops when the site runs out of new links or when `--max-pages` (default 200)
is hit. Links to other domains are never followed. `--depth N` stops after N
hops instead.

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

**Full option reference:** [`professor/capture/MANUAL.md`](professor/capture/MANUAL.md) — a proper `mfp(1)` man page.

---

## Where files land

```
~/code/My-Favorite-Professor/
  py-professor/
    usr-references-provided/     the Markdown notes
    .captures/                   the archives, images and all
    async/                       a subtopic, same shape one level down

~/Downloads/my-favorite-professor/
  py-professor/<title>-<hash>.html    self-contained, opens anywhere
```

The Downloads copy exists so your material isn't hostage to this program —
double-click it, mail it to someone, read it offline. Filenames carry a
content hash, so re-saving a page overwrites cleanly and two pages sharing a
title can't clobber each other.

Set `MFP_LIBRARY` to put the library somewhere else.

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

## Note for macOS

Don't clone this next to a library at `~/code/My-Favorite-Professor` — the
filesystem is case-insensitive, so `my-favorite-professor` and
`My-Favorite-Professor` are the *same directory*, and the source ends up inside
your material. Clone it anywhere else. `install.sh` warns you if you hit this.

---

## Related

This is the capture half of
[my-favorite-professor](https://github.com/tasmall17/my-favorite-professor),
packaged on its own. That project adds a local web app that turns the material
into a course with a Claude alongside it; this one is just the scraper.

## Licence

MIT.
