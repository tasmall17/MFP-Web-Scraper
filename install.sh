#!/usr/bin/env bash
# Install mfp-web-scraper so that `mfp` works in a fresh zsh terminal.
#
#   git clone https://github.com/tasmall17/MFP-Web-Scraper.git
#   cd MFP-Web-Scraper
#   ./install.sh
#
# Everything this touches lives outside the checkout: the tool venv under
# `uv tool dir`, the `mfp` shim in ~/.local/bin, one PATH line in ~/.zshrc, and
# the Chromium download in the shared ms-playwright cache.

set -euo pipefail

TOOL_NAME="mfp-web-scraper"
BIN_DIR="$HOME/.local/bin"
WANT_BROWSER=1
WANT_TIDY=1
ASSUME_YES=0

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'USAGE'
Usage: ./install.sh [options]

  --no-browser   Skip the Chromium download. Uploading .md/.txt/.pdf still
                 works; capturing web pages (mfp -py <url>) does not.
  --no-tidy      Leave the checkout visible in Finder. By default macOS is
                 asked to hide everything here except README.md, so the
                 folder shows your captured material and nothing else.
  -y, --yes      Don't prompt; install uv if it is missing, and tidy.
  -h, --help     Show this message.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --no-browser) WANT_BROWSER=0 ;;
        --no-tidy)    WANT_TIDY=0 ;;
        -y|--yes)     ASSUME_YES=1 ;;
        -h|--help)    usage; exit 0 ;;
        *)            usage >&2; die "unknown option: $1" ;;
    esac
    shift
done

# ---------------------------------------------------------------- the checkout

# Run from the repo the script lives in, not from wherever it was invoked.
REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$REPO_DIR"

[ -f pyproject.toml ] || die "no pyproject.toml in $REPO_DIR -- is this the repo?"
grep -q 'name = "mfp-web-scraper"' pyproject.toml \
    || die "$REPO_DIR does not look like the MFP-Web-Scraper checkout"

say "Installing from $REPO_DIR"

# ------------------------------------------------------------------------- uv

if ! command -v uv >/dev/null 2>&1; then
    say "uv is not installed."
    if [ "$ASSUME_YES" -eq 1 ]; then
        reply=y
    elif [ -t 0 ]; then
        printf 'Install it from https://astral.sh/uv now? [y/N] '
        read -r reply
    else
        reply=n
    fi
    case "$reply" in
        [yY]*)
            curl -LsSf https://astral.sh/uv/install.sh | sh
            # The installer drops uv in ~/.local/bin, which is not on PATH yet.
            export PATH="$BIN_DIR:$PATH"
            hash -r
            ;;
        *)
            die "uv is required. Install it with:
    curl -LsSf https://astral.sh/uv/install.sh | sh
  or, on Fedora 41+:
    sudo dnf install -y uv"
            ;;
    esac
fi

command -v uv >/dev/null 2>&1 || die "uv still not on PATH after install; open a new shell and re-run"
say "uv $(uv --version 2>/dev/null | awk '{print $2}')"

# --------------------------------------------------------------- the tool venv

# --editable so the clone stays the source of truth: git pull updates the
# command, no reinstall. --force makes re-running this script an upgrade.
say "Installing $TOOL_NAME (this fetches Python 3.12 if you don't have it)"
uv tool install --editable . --with patchright --force

TOOL_BIN="$(uv tool dir)/$TOOL_NAME/bin"
[ -x "$TOOL_BIN/mfp" ] || die "expected $TOOL_BIN/mfp after install, but it isn't there"

# ------------------------------------------------------------------------ PATH

# The step that catches zsh users: uv reports success, and `mfp` is still
# "command not found" because ~/.local/bin was never on PATH.
path_has_bin_dir() {
    case ":$PATH:" in *":$BIN_DIR:"*) return 0 ;; *) return 1 ;; esac
}

ensure_path_line() {
    rcfile="$1"
    line='export PATH="$HOME/.local/bin:$PATH"'
    if [ -f "$rcfile" ] && grep -qF '$HOME/.local/bin' "$rcfile"; then
        return 1  # already mentioned; leave the file alone
    fi
    {
        printf '\n# Added by my-favorite-professor install.sh\n'
        printf '%s\n' "$line"
    } >> "$rcfile"
    return 0
}

PATH_EDITED=""
if path_has_bin_dir; then
    say "$BIN_DIR is already on PATH"
else
    for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
        # Only touch bash's rc if bash is actually this user's shell.
        case "$rc" in
            *bashrc) case "${SHELL:-}" in *bash) ;; *) continue ;; esac ;;
        esac
        touch "$rc"
        if ensure_path_line "$rc"; then
            say "Added $BIN_DIR to PATH in $rc"
            PATH_EDITED="${PATH_EDITED}${rc} "
        else
            say "$rc already sets up $BIN_DIR"
        fi
    done
    export PATH="$BIN_DIR:$PATH"
fi

# -------------------------------------------------------------------- Chromium

if [ "$WANT_BROWSER" -eq 1 ]; then
    # `playwright` is an entry point of a *dependency*, so uv does not put it in
    # ~/.local/bin -- it exists only inside the tool venv. Call it by path.
    say "Downloading Chromium for web capture (skip with --no-browser)"
    if ! "$TOOL_BIN/playwright" install chromium; then
        warn "Chromium download failed. Everything except web capture still works."
        warn "Re-run later with: \"$TOOL_BIN/playwright\" install chromium"
    fi
    # patchright is the stealth tier; it shares the ms-playwright cache, so this
    # is usually a no-op. Never fatal -- fetch.py degrades to plain playwright.
    if [ -x "$TOOL_BIN/patchright" ]; then
        "$TOOL_BIN/patchright" install chromium >/dev/null 2>&1 || true
    fi

    # Chromium's system libraries are a separate install from the browser, and
    # `playwright install-deps` only knows apt.
    if [ "$(uname -s)" = "Linux" ]; then
        if command -v dnf >/dev/null 2>&1; then
            say "On Fedora, web capture also needs Chromium's system libraries:"
            cat <<'DNF'
    sudo dnf install -y nss nspr atk at-spi2-atk at-spi2-core cups-libs \
      libdrm libxkbcommon libXcomposite libXdamage libXfixes libXrandr \
      mesa-libgbm alsa-lib pango cairo
DNF
        elif command -v apt-get >/dev/null 2>&1; then
            say "On Debian/Ubuntu, web capture also needs Chromium's system libraries:"
            printf '    sudo "%s" install-deps chromium\n' "$TOOL_BIN/playwright"
        fi
    fi
fi

# ------------------------------------------------------------------ tidy up

# The checkout doubles as a place to capture into, so its own files compete for
# attention with the material. macOS has a per-file "hidden" flag that Finder
# honours, which is the only way to do this without renaming anything: dotting
# `professor/` would break the import, and dotting install.sh or pyproject.toml
# would break the install and how the repo reads on GitHub. Nothing here
# touches git, and `ls` in a terminal is unaffected.
HIDEABLE="pyproject.toml install.sh LICENSE professor tests man-mfp.md"

if [ "$WANT_TIDY" -eq 1 ] && [ "$(uname -s)" = "Darwin" ]; then
    reply=y
    if [ "$ASSUME_YES" -eq 0 ] && [ -t 0 ]; then
        printf 'Hide everything but README.md in Finder, so this folder shows\nonly your captured material? [Y/n] '
        read -r reply
        reply="${reply:-y}"
    fi
    case "$reply" in
        [yY]*)
            for item in $HIDEABLE; do
                [ -e "$REPO_DIR/$item" ] && chflags hidden "$REPO_DIR/$item" 2>/dev/null
            done
            say "Hidden in Finder: $HIDEABLE"
            say "Undo any time with:  chflags nohidden $HIDEABLE"
            ;;
    esac
fi

# ------------------------------------------------------------------- verify it

say "Verifying"
"$TOOL_BIN/mfp" --help >/dev/null 2>&1 || die "$TOOL_BIN/mfp did not run; the install is broken"

RESOLVED="$(command -v mfp 2>/dev/null || true)"
if [ -z "$RESOLVED" ]; then
    warn "mfp is installed but not on PATH in this shell yet."
elif [ "$RESOLVED" != "$BIN_DIR/mfp" ]; then
    warn "mfp resolves to $RESOLVED, not $BIN_DIR/mfp -- something else shadows it."
fi

echo
say "Done. mfp is installed."
echo
if [ -n "$PATH_EDITED" ]; then
    echo "  Open a new terminal first (or run: exec zsh) so PATH picks up."
    echo
fi
cat <<'NEXT'
  mfp -py <url>                   scrape one page into py-University/py-Lecture/
  mfp -py.async <url>             a different lecture, same university
  mfp -py --full <url>            follow every same-site link from there
  mfp -py --repo owner/repo       walk a GitHub tree instead of a page
  mfp --self-test                 check the fetch ladder end to end
  mfp --help                      every option

  mfp --man                       the full manual, offline

  No account, no server, nothing to configure. Captures land in whichever
  directory you run mfp in, so cd somewhere you want the material first.
NEXT
