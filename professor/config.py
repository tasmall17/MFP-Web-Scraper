"""Settings, and the API key.

The key never reaches the browser. It is read here, in the server process, and
used to build the Anthropic client; no endpoint returns it and no template
interpolates it. The browser asks "is a key configured?" and gets a boolean.

That is why the app is a local server rather than a static page: calling
Anthropic straight from the browser needs the
`anthropic-dangerous-direct-browser-access` header and puts your key inside
reach of anything that can run script on the page.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

APP_NAME = "my-favorite-professor"


def _xdg_config_home() -> Path:
    """Where per-user config belongs.

    ~/.config is the XDG default and is also what macOS users of this app
    already have on disk, so it stays the fallback on both platforms rather
    than splitting into a per-OS location. XDG_CONFIG_HOME is honoured where
    it is set, which on a Linux desktop it often is.
    """
    env = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".config"


def _xdg_download_dir() -> Path:
    """The user's real Downloads directory.

    Hardcoding ~/Downloads is right on macOS and only usually right on Linux.
    A desktop install writes the actual location into
    ~/.config/user-dirs.dirs, where it may have been relocated or -- on a
    non-English install -- translated (~/Descargas, ~/Téléchargements). Writing
    to a hardcoded ~/Downloads there would silently create a second, empty
    directory the file manager never shows.

    Order: explicit env var, then the desktop's own record, then the default.
    """
    env = os.environ.get("XDG_DOWNLOAD_DIR", "").strip()
    if env:
        return Path(env).expanduser()

    user_dirs = _xdg_config_home() / "user-dirs.dirs"
    try:
        for line in user_dirs.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("XDG_DOWNLOAD_DIR"):
                continue
            _, _, value = line.partition("=")
            value = value.strip().strip('"')
            if value.startswith("$HOME"):
                return Path.home() / value[len("$HOME"):].lstrip("/")
            if value:
                return Path(value).expanduser()
    except (OSError, UnicodeDecodeError):
        pass  # No desktop file, or not readable. The default is fine.

    return Path.home() / "Downloads"


CONFIG_DIR = _xdg_config_home() / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"

DOWNLOADS_MIRROR = _xdg_download_dir() / APP_NAME


# --------------------------------------------------------------------- config


@dataclass
class Config:
    """The scraper's settings.

    This is the capture half of my-favorite-professor, so the config file it
    reads is the same one -- a machine with both installed shares a single
    library and a single mirror preference. It is read-only here: the full
    app owns writing this file, and the scraper never calls save(), so it
    cannot clobber a key or a model choice it doesn't know about.
    """

    library: str = ""
    # The full app asks about this in Settings and stores the answer. There is
    # no Settings screen here, so "never asked" means on: the second copy is
    # the whole point of a scraper you keep material from. An explicit false in
    # the config file is still honoured.
    mirror_to_downloads: bool = True

    @classmethod
    def load(cls) -> "Config":
        data: dict[str, Any] = {}
        if CONFIG_FILE.is_file():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # A corrupt config is not a crash. Everything in it has a
                # working default.
                data = {}
        known = {f for f in cls.__dataclass_fields__}
        kept = {k: v for k, v in data.items() if k in known}
        # A config written by the full app before the question was answered
        # carries an explicit null, which would otherwise override the default.
        if kept.get("mirror_to_downloads") is None:
            kept.pop("mirror_to_downloads", None)
        return cls(**kept)

    def library_path(self) -> Path:
        from .capture.paths import library_root  # noqa: PLC0415

        if self.library.strip():
            return Path(self.library).expanduser()
        return library_root()
