"""Turning a fetched page into the Markdown note the user actually reads.

This is the visible half of a capture. It is deliberately plain: prose,
headings, links, code blocks, tables. Images are written as ordinary Markdown
links pointing into the hidden assets directory -- they render if you open the
note somewhere that resolves them, and read as harmless text if you don't.

The frontmatter is Obsidian-shaped on purpose, so pointing MFP_LIBRARY at a
vault folder turns every capture into a native note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlparse

import trafilatura
from bs4 import BeautifulSoup
from markdownify import markdownify

from .paths import CAPTURES_DIR


@dataclass
class Extraction:
    title: str
    byline: str | None
    site: str
    markdown: str
    word_count: int


def _meta(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return None


def page_title(soup: BeautifulSoup, url: str) -> str:
    for candidate in (
        _meta(soup, "og:title", "twitter:title"),
        soup.title.string if soup.title and soup.title.string else None,
        soup.h1.get_text(strip=True) if soup.h1 else None,
    ):
        if candidate and candidate.strip():
            return re.sub(r"\s+", " ", candidate).strip()
    path = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return path.replace("-", " ").replace("_", " ").title() or "Untitled"


def _yaml_escape(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _rewrite_images(markdown: str, mapping: dict[str, str], base_url: str,
                    asset_prefix: str) -> str:
    """Repoint every image reference at the local, normalised copy.

    Anything we failed to download keeps its original remote URL rather than
    becoming a broken link.
    """
    if not mapping:
        return markdown

    def replace(match: re.Match) -> str:
        alt, src = match.group(1), match.group(2).strip()
        absolute = urljoin(base_url, src)
        filename = mapping.get(absolute) or mapping.get(src)
        if not filename:
            return match.group(0)
        return f"![{alt}]({asset_prefix}/{filename})"

    return re.sub(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", replace, markdown)


def _body_fallback(html: str) -> str:
    """When trafilatura declines, convert the whole body and move on.

    Noisier than the extractor, but a cluttered note beats an empty one.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "form", "aside"]):
        tag.decompose()
    target = (
        soup.find("article")
        or soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.body
        or soup
    )
    return markdownify(str(target), heading_style="ATX", bullets="-")


def extract(html: str, url: str, *, capture_slug: str,
            asset_mapping: dict[str, str] | None = None,
            topic: str = "", tier: str = "T1",
            from_archive: bool = False) -> Extraction:
    soup = BeautifulSoup(html, "lxml")
    title = page_title(soup, url)
    byline = _meta(soup, "author", "article:author", "og:article:author")
    site = _meta(soup, "og:site_name") or urlparse(url).netloc.removeprefix("www.")

    body = trafilatura.extract(
        html,
        output_format="markdown",
        include_images=True,
        include_links=True,
        include_tables=True,
        include_formatting=True,
        favor_precision=True,
        url=url,
    )
    if not body or len(body.strip()) < 200:
        body = _body_fallback(html)

    body = (body or "").strip()
    asset_prefix = f"{CAPTURES_DIR}/{capture_slug}/assets"
    body = _rewrite_images(body, asset_mapping or {}, url, asset_prefix)
    # Collapse the run-on blank lines both converters like to emit.
    body = re.sub(r"\n{3,}", "\n\n", body)

    captured = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Built as a list of present fields rather than filtering blanks out of a
    # fixed template -- filtering would also eat the deliberate blank lines
    # below, and without the blank line after the attribution quote Markdown's
    # lazy-continuation rule swallows the article's first paragraph into the
    # blockquote.
    fields = [
        ("title", _yaml_escape(title)),
        ("url", url),
        ("site", _yaml_escape(site)),
    ]
    if byline:
        fields.append(("author", _yaml_escape(byline)))
    fields.append(("captured", captured))
    if topic:
        fields.append(("topic", _yaml_escape(topic)))
    fields.append(("tier", tier))
    if from_archive:
        fields.append(("source", "wayback-archive"))
    fields.append(("tags", "[mfp/capture]"))

    attribution = f"> [Original]({url})"
    if byline:
        attribution += f" · {byline}"
    if site:
        attribution += f" · {site}"

    lines = ["---"]
    lines += [f"{key}: {value}" for key, value in fields]
    lines += ["---", "", f"# {title}", "", attribution, "", body, ""]
    text = "\n".join(lines)

    return Extraction(
        title=title,
        byline=byline,
        site=site,
        markdown=text + "\n",
        word_count=len(body.split()),
    )
