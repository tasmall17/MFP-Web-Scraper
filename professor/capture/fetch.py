"""The fetch ladder: T1 plain HTTP -> T2 headless browser -> T3 stealth/archive.

Each tier is tried only when the one below it fails, so the common case (a
static blog, a docs page, Wikipedia) costs one HTTP request and about a second.

On the scope of T3: it makes an automated browser behave like the ordinary
browser you'd have used to read the page yourself, and failing that falls back
to a publicly archived copy. It does not solve CAPTCHAs, use paywall-bypass
tooling, or touch credentials. Pages that stay walled are recorded as failures
rather than fought.
"""

from __future__ import annotations

import ssl
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import certifi
import httpx

TIMEOUT = 25

# A full browser navigation header set. A bare User-Agent gets 403'd by a lot of
# sites that accept this -- they check for Accept-Language and the Sec-Fetch-*
# navigation headers too.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Below this much extracted text, assume we got an SPA shell rather than an
# article and escalate to a real browser.
MIN_ARTICLE_CHARS = 500

WAYBACK_API = "https://archive.org/wayback/available"

# Overlays that bury the article and wreck the PDF. Removed before serializing.
OVERLAY_SELECTORS = [
    "[id*='onetrust']", "[class*='onetrust']",
    "[id*='cookie' i]", "[class*='cookie-banner' i]", "[class*='cookie-consent' i]",
    "[id*='gdpr' i]", "[class*='gdpr' i]",
    "[class*='newsletter-modal' i]", "[class*='paywall-overlay' i]",
    "[class*='subscribe-modal' i]", "[aria-modal='true']",
    "dialog[open]", ".modal-backdrop", "#sp_message_container_",
]


class FetchError(Exception):
    """A tier failed. `stage` is the tier name for the failure CSV."""

    def __init__(self, message: str, stage: str = "T1"):
        super().__init__(message)
        self.stage = stage
        self.reason = message
        # Populated by fetch() with every (tier, reason) it tried, so the
        # failure CSV can record the whole ladder rather than the last rung.
        self.attempts: list[tuple[str, str]] = []


@dataclass
class FetchResult:
    html: str
    final_url: str
    tier: str
    from_archive: bool = False
    archive_timestamp: str | None = None
    background_images: list[str] = field(default_factory=list)


def _ssl_context() -> ssl.SSLContext:
    """certifi-backed context.

    The python.org macOS build frequently ships without its CA bundle wired
    up, which makes every HTTPS request fail verification until you run
    'Install Certificates.command'. Pointing at certifi sidesteps that.
    """
    return ssl.create_default_context(cafile=certifi.where())


def _looks_like_challenge(html: str) -> bool:
    probe = html[:4000].lower()
    markers = (
        "just a moment", "checking your browser", "enable javascript and cookies",
        "cf-browser-verification", "/cdn-cgi/challenge-platform",
        "attention required! | cloudflare", "px-captcha", "please verify you are a human",
    )
    return any(m in probe for m in markers)


def _text_len(html: str) -> int:
    """Cheap proxy for 'did we actually get an article'.

    Script and style bodies are excluded -- an SPA shell is mostly inline JS,
    and counting it would make an empty page look content-rich.
    """
    try:
        from lxml import html as lxml_html  # noqa: PLC0415

        tree = lxml_html.fromstring(html)
        for bad in tree.xpath("//script | //style | //noscript"):
            bad.getparent().remove(bad)
        return len(" ".join(tree.text_content().split()))
    except Exception:
        import re  # noqa: PLC0415

        stripped = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        return len(" ".join(re.sub(r"<[^>]+>", " ", stripped).split()))


# --------------------------------------------------------------------- tier 1


def fetch_t1(url: str) -> FetchResult:
    try:
        with httpx.Client(
            headers=BROWSER_HEADERS,
            timeout=TIMEOUT,
            follow_redirects=True,
            verify=_ssl_context(),
        ) as client:
            resp = client.get(url)
    except httpx.TimeoutException as exc:
        raise FetchError(f"timed out after {TIMEOUT}s", "T1") from exc
    except httpx.HTTPError as exc:
        raise FetchError(f"could not reach URL: {exc}", "T1") from exc

    if resp.status_code == 403:
        raise FetchError("HTTP 403 - blocked automated request", "T1")
    if resp.status_code >= 400:
        raise FetchError(f"HTTP {resp.status_code} {resp.reason_phrase}", "T1")

    html = resp.text
    if _looks_like_challenge(html):
        raise FetchError("bot challenge page returned", "T1")
    if _text_len(html) < MIN_ARTICLE_CHARS:
        raise FetchError("page body looks JS-rendered (little static text)", "T1")

    return FetchResult(html=html, final_url=str(resp.url), tier="T1")


# ------------------------------------------------------------ browser tiers


_PREP_JS = r"""
() => {
  // Pin each image's *resolved* source. Reading the src attribute instead
  // would hand back a 20px srcset placeholder on responsive sites.
  document.querySelectorAll('img').forEach(img => {
    if (img.currentSrc) img.setAttribute('data-mfp-src', img.currentSrc);
  });

  // The hero image is very often a CSS background rather than an <img>.
  const backgrounds = [];
  document.querySelectorAll('*').forEach(el => {
    let bg = '';
    try { bg = getComputedStyle(el).backgroundImage; } catch (e) { return; }
    if (!bg || bg === 'none') return;
    const m = bg.match(/url\(["']?([^"')]+)["']?\)/);
    if (m && m[1] && !m[1].startsWith('data:')) {
      el.setAttribute('data-mfp-bg', m[1]);
      backgrounds.push(m[1]);
    }
  });
  return backgrounds;
}
"""

_STRIP_JS = """
(selectors) => {
  selectors.forEach(sel => {
    let nodes = [];
    try { nodes = document.querySelectorAll(sel); } catch (e) { return; }
    nodes.forEach(n => n.remove());
  });
  // Anything fixed-position and floating above the content is furniture.
  document.querySelectorAll('body *').forEach(el => {
    let s;
    try { s = getComputedStyle(el); } catch (e) { return; }
    if ((s.position === 'fixed' || s.position === 'sticky')
        && parseInt(s.zIndex || '0', 10) > 100) {
      el.remove();
    }
  });
  document.documentElement.style.overflow = 'auto';
  document.body.style.overflow = 'auto';
}
"""

_SCROLL_JS = """
async () => {
  const step = Math.max(300, window.innerHeight * 0.8);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let y = 0;
  for (let i = 0; i < 40; i++) {
    window.scrollTo(0, y);
    await sleep(120);
    y += step;
    if (y > document.body.scrollHeight) break;
  }
  window.scrollTo(0, 0);
  await sleep(200);
}
"""


# Chromium ships as a binary but not as its dependencies, and the failure when
# they are absent is a linker error naming one library at a time -- fix that
# one and the next appears. `playwright install-deps` resolves the whole set,
# but it only knows apt, so on Fedora it exits without doing anything and the
# user is left with the same linker error. Naming the dnf group here turns a
# multi-round guessing game into one command.
_FEDORA_BROWSER_DEPS = (
    "sudo dnf install -y nss nspr atk at-spi2-atk at-spi2-core cups-libs "
    "libdrm libxkbcommon libXcomposite libXdamage libXfixes libXrandr "
    "mesa-libgbm alsa-lib pango cairo"
)


def _launch_hint(exc: Exception) -> str:
    """Turn a bare linker error into the command that fixes it.

    Only fires on Linux, and only for the shapes of failure that actually mean
    "the browser is there but cannot load". A launch failing for some other
    reason should not be answered with an irrelevant install command.
    """
    if not sys.platform.startswith("linux"):
        return ""
    text = str(exc).lower()
    missing_libs = (
        "error while loading shared libraries" in text
        or "cannot open shared object file" in text
        or "missing dependencies" in text
        or "host system is missing" in text
    )
    if missing_libs:
        return (
            "\n\nChromium is installed but cannot load its system libraries. "
            "On Fedora, `playwright install-deps` does not cover dnf; install "
            f"them directly:\n  {_FEDORA_BROWSER_DEPS}"
        )
    if "executable doesn't exist" in text or "looks like playwright" in text:
        return (
            "\n\nThe browser itself is missing. Install it with:"
            "\n  playwright install chromium"
        )
    return ""


def _render_with(driver_module, url: str, tier: str, *, channel: str | None = None):
    """Drive a Playwright-compatible module through one page capture.

    `driver_module` is either `playwright.sync_api` (T2) or `patchright.sync_api`
    (T3a) -- patchright is a drop-in fork, so the same code runs on both.
    """
    launch_kwargs = {"headless": True}
    if channel:
        launch_kwargs["channel"] = channel

    with driver_module.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(**launch_kwargs)
        except Exception as exc:
            raise FetchError(
                f"could not launch browser: {exc}{_launch_hint(exc)}", tier
            ) from exc
        try:
            context = browser.new_context(
                user_agent=BROWSER_HEADERS["User-Agent"],
                locale="en-US",
                viewport={"width": 1440, "height": 900},
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT * 1000)
            except Exception as exc:
                raise FetchError(f"navigation failed: {exc}", tier) from exc

            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass  # networkidle never settles on pages with polling; fine.

            # Lazy-loaded images only materialise once they scroll into view.
            try:
                page.evaluate(_SCROLL_JS)
            except Exception:
                pass

            try:
                page.evaluate(_STRIP_JS, OVERLAY_SELECTORS)
            except Exception:
                pass

            try:
                backgrounds = page.evaluate(_PREP_JS) or []
            except Exception:
                backgrounds = []

            html = page.content()
            final_url = page.url
        finally:
            browser.close()

    if _looks_like_challenge(html):
        raise FetchError("bot challenge persisted in browser", tier)
    if _text_len(html) < MIN_ARTICLE_CHARS:
        raise FetchError("rendered page still had almost no text", tier)

    return FetchResult(
        html=html,
        final_url=final_url,
        tier=tier,
        background_images=[urljoin(final_url, b) for b in backgrounds],
    )


def fetch_t2(url: str) -> FetchResult:
    try:
        from playwright import sync_api  # noqa: PLC0415
    except ImportError as exc:
        raise FetchError("playwright not installed", "T2") from exc
    return _render_with(sync_api, url, "T2")


def fetch_t3a(url: str) -> FetchResult:
    """Stealth-patched driver, and the real Chrome binary rather than bundled."""
    try:
        from patchright import sync_api  # noqa: PLC0415
    except ImportError as exc:
        raise FetchError("patchright not installed (pip install patchright)", "T3a") from exc
    try:
        return _render_with(sync_api, url, "T3a", channel="chrome")
    except FetchError:
        # Real Chrome may not be launchable (in use, missing); retry bundled.
        return _render_with(sync_api, url, "T3a")


def fetch_t3b(url: str) -> FetchResult:
    """Last resort: a publicly archived snapshot from the Wayback Machine."""
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True,
                          verify=_ssl_context()) as client:
            probe = client.get(WAYBACK_API, params={"url": url},
                               headers={"User-Agent": BROWSER_HEADERS["User-Agent"]})
            probe.raise_for_status()
            snapshot = (
                probe.json().get("archived_snapshots", {}).get("closest") or {}
            )
            if not snapshot.get("available") or not snapshot.get("url"):
                raise FetchError("no archived snapshot available", "T3b")

            # id_ returns the original page rather than the Wayback chrome.
            archive_url = snapshot["url"].replace("/http", "id_/http", 1)
            resp = client.get(archive_url, headers=BROWSER_HEADERS)
            resp.raise_for_status()
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"archive lookup failed: {exc}", "T3b") from exc

    return FetchResult(
        html=resp.text,
        final_url=str(resp.url),
        tier="T3b",
        from_archive=True,
        archive_timestamp=snapshot.get("timestamp"),
    )


# ---------------------------------------------------------------- the ladder


def fetch(url: str, *, max_tier: str = "T3", on_tier=None) -> FetchResult:
    """Walk the ladder until a tier produces a usable page.

    Raises FetchError carrying the *last* tier's stage and reason, which is
    what lands in failed-attempts.csv.
    """
    if not urlparse(url).scheme:
        url = "https://" + url

    tiers = [("T1", fetch_t1), ("T2", fetch_t2)]
    if max_tier == "T3":
        tiers += [("T3a", fetch_t3a), ("T3b", fetch_t3b)]

    attempts: list[tuple[str, str]] = []
    for name, fn in tiers:
        if on_tier:
            on_tier(name)
        try:
            return fn(url)
        except FetchError as exc:
            attempts.append((name, exc.reason))
            # Be polite between escalations rather than hammering.
            time.sleep(0.6)
        except Exception as exc:  # a driver blowing up shouldn't kill the run
            attempts.append((name, f"{type(exc).__name__}: {exc}"))
            time.sleep(0.6)

    # Report the whole ladder, not just the last rung. The final tier is
    # always the archive lookup, so "no archived snapshot available" would be
    # the recorded reason for every failure -- which tells you nothing about
    # why the live page didn't work. This CSV exists to be troubleshooted by
    # hand later, so it needs to say the page 403'd, not that the Wayback
    # Machine hadn't heard of it.
    summary = "; ".join(f"{tier}: {reason}" for tier, reason in attempts)
    # stage = how far it got before giving up.
    error = FetchError(summary or "all tiers failed", attempts[-1][0] if attempts else "T1")
    error.attempts = attempts
    raise error
