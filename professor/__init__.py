"""mfp-web-scraper -- a web page becomes a note you can actually read.

Give it a URL and it returns two things: a readable Markdown note, and a
hidden archive holding the page with its images normalised and inlined, so
the material still works offline.

    capture/    the whole scraper -- fetch ladder, extraction, assets, CLI
    mirror      the second copy, into ~/Downloads
    markdown    Markdown -> HTML for the compiled archive
    config      where the library lives, and whether to mirror

This is the capture half of my-favorite-professor, packaged on its own.
There is no server, no API key, and nothing that talks to Anthropic.
"""

from __future__ import annotations

__version__ = "0.1.0"
