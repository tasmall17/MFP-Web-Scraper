# my-favorite-professor

Learn a subject from material *you* chose, with a Claude that gets better at
explaining things to you specifically.

You bring the references — Markdown, text, PDFs, or web pages you saved while
reading them. It maps them into a course you work through in the browser, and
puts a Professor-Claude next to whatever section you're on. Over time it works
out what makes an idea land for *you* — the analogy that clicked, the level of
detail you actually want — and keeps that in a profile you own and can hand to
any other Claude.

The name is a file extension, because the subject is:

```
my-favorite-professor.sh      learn the shell
my-favorite-professor.py      learn Python
my-favorite-professor.sql     learn just enough SQL to finish the thing you're building
```

Nothing here is subject-specific. Upload references, get a course.

---

## Install

Needs Python 3.12+ and an [Anthropic API key](https://console.anthropic.com/).

```sh
git clone https://github.com/tasmall17/my-favorite-professor.git
cd my-favorite-professor
uv tool install --editable . --with patchright
playwright install chromium          # only needed for capturing web pages
```

Then:

```sh
my-favorite-professor serve
```

It opens in your browser. Paste your API key into Settings on first run.

> `mfp` is installed as a shorter alias for the same command.

---

## The two ways material gets in

**Upload**, from Settings → Upload materials. `.md`, `.txt`, `.pdf`.

**Capture**, from the command line, while you're reading something:

```sh
mfp -py https://realpython.com/primer-on-python-decorators/
```

Topic flags are invented on the spot — `-py` files into `py-professor/`, and
typing `-python` later lands in the same place rather than making a second
directory. The full capture manual is in
[`professor/capture/MANUAL.md`](professor/capture/MANUAL.md).

Either way you get the same thing: a readable Markdown note, plus a hidden
archive holding the page with its images normalised and inlined, so the
material still works offline and Claude can actually see the figures.

---

## Where things live

Three separate places, deliberately. None of them is inside this repo.

```
~/code/My-Favorite-Professor/        your material
  py-professor/
    usr-references-provided/         what you chose
    claude-references-provided/      what Claude fetched to fill a gap
    .captures/                       the archives, images and all
    .mfp-course/syllabus.json        the generated course map

~/.my-favorite-professor/            your learning profile
  usr-learning-profile/
    profile.md                       the artifact you hand to another Claude
    evidence/                        the observations behind it

~/Downloads/my-favorite-professor/   the second copy
  py-professor/<title>-<hash>.html   self-contained, opens anywhere
```

**The profile is global on purpose.** It is about how *you* understand things,
not about any one subject, so it lives outside any particular library and
carries over to every topic you ever study. `mfp profile export` bundles it up.

**The second copy** exists so your material isn't hostage to this program. The
Downloads copies are self-contained HTML — double-click them, read them on a
plane, mail them to someone. Filenames carry the capture's content hash so
re-saving a page overwrites cleanly and two pages that share a title can't
clobber each other.

Set `MFP_LIBRARY` to put your material somewhere else.

---

## Your API key

Stays in `~/.config/my-favorite-professor/config.json`, mode `0600`, and is read
only by the local server process. It is never sent to the browser, never
embedded in a page, and never returned by any endpoint — the front end can only
ask *whether* a key is configured.

That's the reason this is a local server and not a single HTML file: calling
Anthropic from the browser needs the `anthropic-dangerous-direct-browser-access`
header and puts your key within reach of anything that can run script on the
page.

`ANTHROPIC_API_KEY` is used as a fallback if you'd rather not store it at all.

Bring your own key — this talks to Anthropic as you, and nothing routes through
anyone else.

---

## Picking a model

In Settings, per session:

| | |
|---|---|
| **Opus** | Break it right down. Best when the topic is new to you. |
| **Sonnet** | Quick and capable. Good for recap and revision. |
| **Haiku** | Fastest and cheapest. Short definitions and lookups. |

Opus and Sonnet also take an **effort** setting, from `low` to `max` — how hard
Claude works before answering. Haiku doesn't support it, so the control
disappears when you pick Haiku rather than silently doing nothing.

---

## Note for macOS

Don't clone this repo as `~/code/my-favorite-professor` next to a library at
`~/code/My-Favorite-Professor`. The filesystem is case-insensitive, so those are
the *same directory*, and you'll end up with the app's source inside your
material. The app detects and refuses to treat a source checkout as a library,
but the tidy fix is to keep the two apart — clone it as
`my-favorite-professor-app`, or anywhere outside `~/code`.

---

## Licence

MIT.
