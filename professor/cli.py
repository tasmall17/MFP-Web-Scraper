"""Command line entry point, exposed as `my-favorite-professor` and `mfp`.

    my-favorite-professor serve                    open the app
    mfp -py https://realpython.com/decorators      save a page while reading it
    mfp --topics                                   what subjects exist

Two things share one command because they are two halves of one habit: you
capture a page the moment you find it, and you study it later in the app.

The capture half is the vendored tool's argument handling, unchanged --
including the trick that makes topic flags work. argparse cannot accept
arbitrary unknown flags, so sys.argv is pre-scanned and the first unrecognised
flag-shaped token is taken as the topic. Subcommands are matched before that
scan runs, so `serve` is never mistaken for a URL.
"""

from __future__ import annotations

import sys

from .capture.cli import main as capture_main

SUBCOMMANDS = {"serve", "profile"}


def _serve(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="my-favorite-professor serve",
        description="Run the app on localhost and open it in your browser.",
    )
    parser.add_argument("--port", type=int, default=8765,
                        help="preferred port (default 8765; a free one is "
                             "chosen if it's taken)")
    parser.add_argument("--no-open", action="store_true",
                        help="don't open a browser window")
    args = parser.parse_args(argv)

    from .server import serve

    try:
        return serve(port=args.port, open_browser=not args.no_open)
    except KeyboardInterrupt:
        print("\n  stopped")
        return 0


def _profile(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="my-favorite-professor profile",
        description="Your learning profile: where it is, and how to take it "
                    "somewhere else.",
    )
    parser.add_argument("action", nargs="?", default="show",
                        choices=["show", "path", "export"])
    parser.add_argument("--to", metavar="PATH",
                        help="with export, where to write the bundle")
    args = parser.parse_args(argv)

    from .config import PROFILE_DIR

    if args.action == "path":
        print(PROFILE_DIR)
        return 0

    if args.action == "export":
        import shutil

        if not PROFILE_DIR.is_dir():
            print("  no profile yet -- it builds as you study", file=sys.stderr)
            return 1
        target = args.to or str(PROFILE_DIR.parent / "usr-learning-profile")
        archive = shutil.make_archive(str(target), "zip", root_dir=PROFILE_DIR)
        print(f"  {archive}")
        return 0

    profile = PROFILE_DIR / "profile.md"
    if not profile.is_file():
        print(f"  no profile yet -- it builds as you study")
        print(f"  it will appear at: {profile}")
        return 0
    print(profile.read_text(encoding="utf-8"))
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    if raw and raw[0] in SUBCOMMANDS:
        return {"serve": _serve, "profile": _profile}[raw[0]](raw[1:])

    # No arguments at all is the first thing someone types. Point at the app
    # rather than dumping capture flags at them.
    if not raw:
        print()
        print("  my-favorite-professor serve    open the app")
        print("  mfp -py <url>                  save a page while you're reading it")
        print("  mfp --topics                   what subjects you have")
        print()
        print("  --help for everything the capture side can do")
        return 0

    return capture_main(raw)


if __name__ == "__main__":
    raise SystemExit(main())
