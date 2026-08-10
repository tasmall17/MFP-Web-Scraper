"""A small Markdown renderer, used in two places.

The reading pane needs Markdown as HTML, and so does the archived page.html
that the Downloads copy is compiled from. Rather than take a dependency for
this, or render in the browser and have the two copies drift, both go through
here.

Scope is deliberately the subset that study material actually uses: headings,
paragraphs, fenced and indented code, lists, blockquotes, rules, tables,
images, links, and inline emphasis. Reference-style links, footnotes and inline
HTML pass through as literal text.

**Everything is HTML-escaped before any markup is applied.** The input is a
file you chose, rendered in your own browser, so this is not the primary
defence -- but material arrives here from PDFs and from pages Claude fetched
off the open web, and neither is something to inject into a document unescaped.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)\s*([\w+-]*)\s*$")
_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:-]*-[\s:|-]*\|?\s*$")

# Inline. Order matters: code spans are pulled out first so their contents are
# never treated as emphasis or link syntax.
_CODE_SPAN = re.compile(r"`([^`]+)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"([^\"]*)\")?\s*\)")
_LINK = re.compile(r"\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+\"([^\"]*)\")?\s*\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__", re.DOTALL)
_ITALIC = re.compile(r"(?<![*\w])\*(?=\S)([^*]+?)(?<=\S)\*(?!\*)"
                     r"|(?<![_\w])_(?=\S)([^_]+?)(?<=\S)_(?!\w)")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_BARE_URL = re.compile(r"(?<![\"'=(\w])(https?://[^\s<>\")]+)")

# Anything of the form `scheme:` must be on the allow-list. A bare relative
# reference (`assets/img.png`, `#anchor`, `../notes.md`) has no scheme and is
# always fine.
_SCHEME = re.compile(r"\A([a-zA-Z][a-zA-Z0-9+.\-]*)\s*:")
_ALLOWED_SCHEMES = frozenset({"http", "https", "mailto"})
_URL_JUNK = re.compile(r"[\x00-\x20\x7f]")


@dataclass
class Document:
    frontmatter: dict[str, str]
    body: str
    html: str
    title: str


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Peel off the YAML-ish frontmatter the capture layer writes.

    Not a YAML parser -- it handles the flat `key: value` block this
    application produces and leaves anything stranger alone.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith((" ", "\t", "-")):
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        meta[key.strip()] = value
    return meta, text[match.end():]


def _attr(value: str) -> str:
    """Make a string safe to sit inside a double-quoted attribute.

    render_inline() escapes with quote=False, so `&` and the angle brackets are
    already handled but `"` is not -- and a quote inside a URL would otherwise
    close the attribute and let the rest of the URL become markup.
    """
    return value.replace('"', "&quot;")


def _safe_url(raw: str) -> str:
    """Reject anything that isn't an ordinary document reference.

    `javascript:` and `data:` URLs in fetched material have no business
    becoming live attributes in the reading pane. Entities are unescaped and
    control characters stripped before the check, because `java&#9;script:` and
    `java\\tscript:` are both things browsers will happily execute.
    """
    # Unescape until it stops changing. render_inline() has already escaped the
    # text once, so a `&#9;` in the source arrives here as `&amp;#9;` and a
    # single unescape leaves the entity intact -- the tab only appears on the
    # second pass. Bounded so a pathological input can't spin.
    candidate = raw
    for _ in range(4):
        unescaped = html.unescape(candidate)
        if unescaped == candidate:
            break
        candidate = unescaped
    candidate = _URL_JUNK.sub("", candidate).strip()
    scheme = _SCHEME.match(candidate)
    if scheme and scheme.group(1).lower() not in _ALLOWED_SCHEMES:
        return "#"
    return _attr(raw)


def render_inline(text: str) -> str:
    """Escape, then apply inline markup. Code spans are protected first."""
    spans: list[str] = []

    def stash(match: re.Match) -> str:
        spans.append(html.escape(match.group(1), quote=False))
        return f"\x00{len(spans) - 1}\x00"

    text = _CODE_SPAN.sub(stash, text)
    text = html.escape(text, quote=False)

    def image(match: re.Match) -> str:
        alt, src, title = _attr(match.group(1)), _safe_url(match.group(2)), match.group(3)
        extra = f' title="{_attr(title)}"' if title else ""
        return f'<img src="{src}" alt="{alt}"{extra} loading="lazy">'

    def link(match: re.Match) -> str:
        label, href, title = match.group(1), _safe_url(match.group(2)), match.group(3)
        extra = f' title="{_attr(title)}"' if title else ""
        return (f'<a href="{href}"{extra} rel="noopener noreferrer" '
                f'target="_blank">{label}</a>')

    text = _IMAGE.sub(image, text)
    text = _LINK.sub(link, text)
    text = _BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text)
    text = _ITALIC.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text)
    text = _STRIKE.sub(lambda m: f"<del>{m.group(1)}</del>", text)
    text = _BARE_URL.sub(
        lambda m: f'<a href="{m.group(1)}" rel="noopener noreferrer" '
                  f'target="_blank">{m.group(1)}</a>',
        text,
    )

    for index, code in enumerate(spans):
        text = text.replace(f"\x00{index}\x00", f"<code>{code}</code>")
    return text


class _Renderer:
    """Line-at-a-time block renderer.

    Written as a class only so the block state (open list stack, whether a
    paragraph is being accumulated) stays out of module scope.
    """

    def __init__(self) -> None:
        self.out: list[str] = []
        self.para: list[str] = []
        self.stack: list[tuple[str, int]] = []  # (tag, indent)

    # -- block bookkeeping ------------------------------------------------

    def flush_para(self) -> None:
        if self.para:
            self.out.append(f"<p>{render_inline(' '.join(self.para))}</p>")
            self.para = []

    def close_lists(self, to_indent: int = -1) -> None:
        while self.stack and self.stack[-1][1] > to_indent:
            self.out.append(f"</{self.stack.pop()[0]}>")

    def close_all(self) -> None:
        self.flush_para()
        self.close_lists()

    def open_list(self, tag: str, indent: int) -> None:
        if not self.stack or self.stack[-1][1] < indent:
            self.out.append(f"<{tag}>")
            self.stack.append((tag, indent))
        elif self.stack[-1][0] != tag:
            self.out.append(f"</{self.stack.pop()[0]}>")
            self.out.append(f"<{tag}>")
            self.stack.append((tag, indent))

    # -- the loop ---------------------------------------------------------

    def run(self, text: str) -> str:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        index = 0
        while index < len(lines):
            line = lines[index]

            fence = _FENCE.match(line)
            if fence:
                index = self._code_fence(lines, index, fence)
                continue

            if not line.strip():
                self.flush_para()
                self.close_lists()
                index += 1
                continue

            if _RULE.match(line):
                self.close_all()
                self.out.append("<hr>")
                index += 1
                continue

            heading = _HEADING.match(line)
            if heading:
                self.close_all()
                level = len(heading.group(1))
                body = render_inline(heading.group(2).strip())
                self.out.append(f"<h{level}>{body}</h{level}>")
                index += 1
                continue

            if line.lstrip().startswith(">"):
                index = self._blockquote(lines, index)
                continue

            if "|" in line and index + 1 < len(lines) and _TABLE_SEP.match(lines[index + 1]):
                index = self._table(lines, index)
                continue

            ordered = _OL.match(line)
            unordered = _UL.match(line)
            if ordered or unordered:
                self.flush_para()
                indent = len((ordered or unordered).group(1).expandtabs(4))
                self.close_lists(indent)
                self.open_list("ol" if ordered else "ul", indent)
                content = ordered.group(3) if ordered else unordered.group(2)
                self.out.append(f"<li>{render_inline(content.strip())}</li>")
                index += 1
                continue

            self.para.append(line.strip())
            index += 1

        self.close_all()
        return "\n".join(self.out)

    # -- multi-line blocks ------------------------------------------------

    def _code_fence(self, lines: list[str], index: int, fence: re.Match) -> int:
        self.close_all()
        marker, lang = fence.group(1), fence.group(2)
        body: list[str] = []
        index += 1
        while index < len(lines):
            closing = _FENCE.match(lines[index])
            if closing and closing.group(1) == marker:
                index += 1
                break
            body.append(lines[index])
            index += 1
        attr = f' class="language-{html.escape(lang, quote=True)}"' if lang else ""
        code = html.escape("\n".join(body), quote=False)
        self.out.append(f"<pre><code{attr}>{code}</code></pre>")
        return index

    def _blockquote(self, lines: list[str], index: int) -> int:
        self.close_all()
        body: list[str] = []
        while index < len(lines):
            quoted = _QUOTE.match(lines[index].lstrip())
            if not quoted:
                break
            body.append(quoted.group(1))
            index += 1
        inner = _Renderer().run("\n".join(body))
        self.out.append(f"<blockquote>{inner}</blockquote>")
        return index

    def _table(self, lines: list[str], index: int) -> int:
        self.close_all()

        def cells(row: str) -> list[str]:
            return [c.strip() for c in row.strip().strip("|").split("|")]

        header = cells(lines[index])
        index += 2  # header plus the separator row
        rows: list[list[str]] = []
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            rows.append(cells(lines[index]))
            index += 1

        parts = ["<table><thead><tr>"]
        parts += [f"<th>{render_inline(c)}</th>" for c in header]
        parts.append("</tr></thead><tbody>")
        for row in rows:
            parts.append("<tr>")
            parts += [f"<td>{render_inline(c)}</td>" for c in row]
            parts.append("</tr>")
        parts.append("</tbody></table>")
        self.out.append("".join(parts))
        return index


def to_html(markdown_text: str) -> str:
    return _Renderer().run(markdown_text)


def parse(text: str) -> Document:
    """Split frontmatter, render the body, and work out a display title."""
    meta, body = split_frontmatter(text)
    title = meta.get("title", "").strip()
    if not title:
        for line in body.splitlines():
            heading = _HEADING.match(line)
            if heading:
                title = heading.group(2).strip()
                break
    return Document(
        frontmatter=meta,
        body=body,
        html=to_html(body),
        title=title or "Untitled",
    )
