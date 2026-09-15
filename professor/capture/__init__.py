"""The capture layer: turn a web page into a study bundle.

The public surface:

    from professor.capture import capture_url, compile_capture

    result = capture_url("https://example.com/article", topic="py")
    pdf = compile_capture(result.capture_dir, as_pdf=True)

Anything producing the same bundle from a local file instead of a fetched page
reaches one level deeper and calls `write_capture` directly.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["capture_url", "compile_capture", "CaptureResult", "FetchError"]


def capture_url(url: str, topic: str | None = None, *, root: Path | None = None,
                max_tier: str = "T3", quiet: bool = True):
    """Fetch, archive and file a URL. Returns a CaptureResult.

    Raises FetchError if no tier could retrieve the page -- callers that want
    the failure recorded should use the CLI path or call journal.record_failure
    themselves.
    """
    from .capture import write_capture
    from .fetch import fetch
    from .paths import INBOX_TOPIC, ensure_library
    from .topics import TopicRegistry

    library = ensure_library(root)
    registry = TopicRegistry(library)
    resolution = registry.resolve(topic or INBOX_TOPIC)
    result = fetch(url, max_tier=max_tier)
    return write_capture(
        result,
        lecture_dir=resolution.directory,
        topic=resolution.label,
        original_url=url,
        quiet=quiet,
    )


def compile_capture(capture_dir: Path, *, as_pdf: bool = False,
                    output: Path | None = None) -> Path:
    """Rebuild a capture into a single file. Offline; never touches the network."""
    from .compile import compile_html, compile_pdf

    return (compile_pdf if as_pdf else compile_html)(capture_dir, output)


def __getattr__(name: str):
    # Deferred so importing the package doesn't drag in httpx/playwright.
    if name == "CaptureResult":
        from .capture import CaptureResult

        return CaptureResult
    if name == "FetchError":
        from .fetch import FetchError

        return FetchError
    raise AttributeError(name)
