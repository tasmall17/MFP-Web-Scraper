"""Downloading, filtering and normalising a page's images.

The point of this module is the Claude-facing copy. A news page carries a
couple hundred <img> elements of which maybe six matter, and modern sites
serve AVIF almost exclusively -- so the job is to throw away the noise and
convert what's left into something a model can actually open.

Best-effort by design: a page that loses a few images is still a good capture.
Only a page with no readable content at all counts as a failure.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image

from .fetch import BROWSER_HEADERS, _ssl_context

# Anything smaller than this in either dimension is an icon, a spacer or a
# tracking pixel -- never article content.
MIN_DIMENSION = 100
# Downscale beyond this and you're paying context for detail nobody reads.
MAX_EDGE = 1500
MAX_ASSETS = 150
MAX_TOTAL_BYTES = 80 * 1024 * 1024
DOWNLOAD_TIMEOUT = 20

# Formats we re-encode to PNG because model-side support is uneven.
TRANSCODE_TO_PNG = {"AVIF", "WEBP", "HEIF", "HEIC"}

_MAGIC = [
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
]


@dataclass
class AssetReport:
    """What survived, what didn't, and why -- surfaced rather than swallowed."""

    mapping: dict[str, str] = field(default_factory=dict)  # source URL -> filename
    kept: int = 0
    failed: int = 0
    skipped_small: int = 0
    skipped_duplicate: int = 0
    skipped_cap: int = 0

    @property
    def dropped(self) -> int:
        return self.skipped_small + self.skipped_duplicate + self.skipped_cap

    def summary(self) -> str:
        bits = [f"{self.kept} kept"]
        if self.failed:
            bits.append(f"{self.failed} failed")
        if self.skipped_small:
            bits.append(f"{self.skipped_small} too small")
        if self.skipped_duplicate:
            bits.append(f"{self.skipped_duplicate} duplicate")
        if self.skipped_cap:
            bits.append(f"{self.skipped_cap} over cap")
        return ", ".join(bits)


def sniff_extension(data: bytes, content_type: str = "") -> str:
    """Determine the real format from bytes, never from the URL.

    URLs lie constantly -- CDNs serve WebP from a .jpg path and AVIF from a
    query string.
    """
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    if data[4:12] in (b"ftypavif", b"ftypavis") or data[4:8] == b"ftyp" and b"avif" in data[:32]:
        return "avif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:5] == b"<?xml" or data[:4] == b"<svg":
        return "svg"
    ct = (content_type or "").split(";")[0].strip().lower()
    return {
        "image/jpeg": "jpg", "image/png": "png", "image/gif": "gif",
        "image/webp": "webp", "image/avif": "avif", "image/svg+xml": "svg",
    }.get(ct, "bin")


def _best_from_srcset(srcset: str, base_url: str) -> str | None:
    """Pick the highest-resolution candidate out of a srcset attribute."""
    best, best_score = None, -1.0
    for part in srcset.split(","):
        chunk = part.strip().split()
        if not chunk:
            continue
        url = chunk[0]
        score = 0.0
        if len(chunk) > 1:
            desc = chunk[1]
            try:
                score = float(desc[:-1]) if desc[-1] in "wx" else 0.0
            except ValueError:
                score = 0.0
        if score > best_score:
            best, best_score = url, score
    return urljoin(base_url, best) if best else None


def collect_image_urls(soup, base_url: str, extra: list[str] | None = None) -> list[str]:
    """Every plausible image reference on the page, in document order."""
    urls: list[str] = []

    def add(candidate: str | None) -> None:
        if not candidate:
            return
        candidate = candidate.strip()
        if not candidate or candidate.startswith(("data:", "javascript:", "about:")):
            return
        absolute = urljoin(base_url, candidate)
        if urlparse(absolute).scheme in ("http", "https") and absolute not in urls:
            urls.append(absolute)

    for img in soup.find_all("img"):
        # data-mfp-src is img.currentSrc, captured in the live page. It is the
        # only source that reflects what the browser actually chose.
        add(img.get("data-mfp-src"))
        if img.get("srcset"):
            add(_best_from_srcset(img["srcset"], base_url))
        for attr in ("src", "data-src", "data-original", "data-lazy-src"):
            add(img.get(attr))

    for source in soup.find_all("source"):
        if source.get("srcset"):
            add(_best_from_srcset(source["srcset"], base_url))

    for el in soup.select("[data-mfp-bg]"):
        add(el.get("data-mfp-bg"))

    for prop in ("og:image", "twitter:image"):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find(
            "meta", attrs={"name": prop}
        )
        if tag:
            add(tag.get("content"))

    for candidate in extra or []:
        add(candidate)

    return urls


def _normalise(data: bytes, ext: str) -> tuple[bytes, str, tuple[int, int]] | None:
    """Transcode and downscale. Returns None when the image should be dropped."""
    if ext == "svg":
        # Vector, tiny, and already text -- keep verbatim, no size checks.
        return data, "svg", (0, 0)

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        return None

    width, height = image.size
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        return None

    fmt = (image.format or "").upper()
    changed = False

    if max(width, height) > MAX_EDGE:
        scale = MAX_EDGE / max(width, height)
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.LANCZOS,
        )
        changed = True

    if fmt in TRANSCODE_TO_PNG or changed:
        out_ext = "png" if fmt in TRANSCODE_TO_PNG else {"JPEG": "jpg"}.get(fmt, (fmt or "PNG").lower())
        save_fmt = "PNG" if out_ext == "png" else ("JPEG" if out_ext == "jpg" else out_ext.upper())
        if save_fmt == "JPEG" and image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        elif save_fmt == "PNG" and image.mode == "CMYK":
            image = image.convert("RGB")
        buffer = io.BytesIO()
        try:
            image.save(buffer, format=save_fmt, optimize=True)
        except Exception:
            image.convert("RGB").save(buffer, format="PNG")
            out_ext = "png"
        return buffer.getvalue(), out_ext, image.size

    return data, ext, image.size


def download_assets(urls: list[str], dest: Path, *, quiet: bool = False) -> AssetReport:
    """Fetch, filter, normalise and write every usable image into `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    report = AssetReport()
    seen_hashes: dict[str, str] = {}
    total_bytes = 0
    index = 0

    with httpx.Client(
        headers=BROWSER_HEADERS,
        timeout=DOWNLOAD_TIMEOUT,
        follow_redirects=True,
        verify=_ssl_context(),
    ) as client:
        for url in urls:
            if report.kept >= MAX_ASSETS or total_bytes >= MAX_TOTAL_BYTES:
                report.skipped_cap += 1
                continue
            try:
                resp = client.get(url)
                resp.raise_for_status()
                raw = resp.content
            except Exception:
                report.failed += 1
                continue

            ext = sniff_extension(raw, resp.headers.get("content-type", ""))
            if ext == "bin":
                report.failed += 1
                continue

            normalised = _normalise(raw, ext)
            if normalised is None:
                report.skipped_small += 1
                continue
            data, out_ext, _ = normalised

            digest = hashlib.sha256(data).hexdigest()
            if digest in seen_hashes:
                # Same bytes under a different URL -- point both at one file.
                report.mapping[url] = seen_hashes[digest]
                report.skipped_duplicate += 1
                continue

            index += 1
            filename = f"img-{index:03d}-{digest[:8]}.{out_ext}"
            try:
                (dest / filename).write_bytes(data)
            except OSError:
                report.failed += 1
                continue

            seen_hashes[digest] = filename
            report.mapping[url] = filename
            report.kept += 1
            total_bytes += len(data)

    if not quiet and report.dropped:
        print(f"  images: {report.summary()}")
    return report
