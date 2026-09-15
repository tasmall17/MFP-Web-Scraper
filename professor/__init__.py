"""mfp-web-scraper -- a web page becomes a note you can actually read.

Give it a URL and it returns two things: a readable Markdown note, and a
hidden archive holding the page with its images normalised and inlined, so
the material still works offline.

    capture/    the whole scraper -- fetch ladder, extraction, assets, CLI
    mirror      the self-contained copy that sits beside the note
    markdown    Markdown -> HTML for the compiled archive

Captures land in the directory you run it from. There is no server, no
account, and nothing that talks to a network service other than the site you
pointed it at.
"""

from __future__ import annotations

__version__ = "0.1.0"
