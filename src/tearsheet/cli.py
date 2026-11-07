"""The tearsheet command."""

import argparse
import sys
from collections.abc import Sequence

from tearsheet import __version__
from tearsheet.core import paths


def _login() -> int:
    # Imported here so starting the server doesn't pay for Playwright.
    from playwright.sync_api import Error as PlaywrightError

    from tearsheet.login import LoginTimeoutError, login

    print("Sign in to Tijori in the browser window that opens.")
    path = paths.session_path()
    try:
        login(path)
    except LoginTimeoutError as exc:
        print(exc, file=sys.stderr)
        return 1
    except PlaywrightError as exc:
        print(f"The browser stopped before sign-in finished: {exc}", file=sys.stderr)
        print("If Chromium is missing, run: playwright install chromium", file=sys.stderr)
        return 1
    print(f"Signed in. Session saved to {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tearsheet", description="Local MCP server for researching Indian stocks."
    )
    parser.add_argument("--version", action="version", version=f"tearsheet {__version__}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="run the MCP server over stdio (the default)")
    commands.add_parser("login", help="sign in to Tijori in a browser window")
    args = parser.parse_args(argv)

    if args.command == "login":
        return _login()

    from tearsheet.server import build_server

    build_server().run()
    return 0
