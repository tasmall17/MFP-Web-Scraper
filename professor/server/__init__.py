"""The local web application.

A server rather than a static page for one reason: the API key. See config.py.
"""

from __future__ import annotations

from .app import create_app, serve

__all__ = ["create_app", "serve"]
