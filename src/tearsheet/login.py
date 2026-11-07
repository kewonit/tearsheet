"""Sign in to Tijori through a real browser window.

The user types their password into Tijori's own page, so Tearsheet never sees
it. Only the resulting cookies are saved.
"""

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from tearsheet.core.session import SESSION_COOKIE, write_session

TIJORI_URL = "https://www.tijorifinance.com/"
LOGIN_TIMEOUT_S = 300
POLL_INTERVAL_MS = 1000


class LoginTimeoutError(Exception):
    """The user didn't finish signing in before the time limit."""


def login(
    path: Path,
    *,
    url: str = TIJORI_URL,
    timeout_s: float = LOGIN_TIMEOUT_S,
    headless: bool = False,
    poll_ms: int = POLL_INTERVAL_MS,
) -> None:
    """Open a browser, wait for a session cookie, then save the session."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if any(c["name"] == SESSION_COOKIE for c in context.cookies(url)):
                    write_session(context.storage_state(), path)
                    return
                page.wait_for_timeout(poll_ms)
            raise LoginTimeoutError(f"No sign-in within {timeout_s:g} seconds. Nothing was saved.")
        finally:
            browser.close()
