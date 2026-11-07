"""Sign in to Tijori through a real browser window.

The user signs in on Tijori's own page, so Tearsheet never sees their password.
Only the resulting cookies are saved.
"""

import time
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from tearsheet.core.session import SESSION_COOKIE, write_session

TIJORI_SIGN_IN_URL = "https://www.tijorifinance.com/account/signin/"
LOGIN_TIMEOUT_S = 600
POLL_INTERVAL_S = 1.0


class LoginTimeoutError(Exception):
    """The user didn't finish signing in before the time limit."""


class LoginCancelledError(Exception):
    """The browser closed before sign-in finished."""


def _has_session_cookie(context: BrowserContext, url: str) -> bool:
    return any(cookie["name"] == SESSION_COOKIE for cookie in context.cookies(url))


def wait_for_session(
    context: BrowserContext, path: Path, *, url: str, timeout_s: float, poll_s: float
) -> None:
    """Wait for a session cookie, then save the session.

    This watches the browser session rather than one tab, because sign-in can
    redirect through other sites or open popups.
    """
    cancelled = "The browser closed before sign-in finished. Nothing was saved."
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if _has_session_cookie(context, url):
                write_session(context.storage_state(), path)
                return
        except PlaywrightError as exc:
            raise LoginCancelledError(cancelled) from exc
        if not context.pages:
            raise LoginCancelledError(cancelled)
        time.sleep(poll_s)
    raise LoginTimeoutError(f"No sign-in within {timeout_s:g} seconds. Nothing was saved.")


def login(
    path: Path,
    *,
    url: str = TIJORI_SIGN_IN_URL,
    timeout_s: float = LOGIN_TIMEOUT_S,
    headless: bool = False,
    poll_s: float = POLL_INTERVAL_S,
) -> None:
    """Open a browser for the user to sign in, then save the session."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            context = browser.new_context()
            context.new_page().goto(url, wait_until="domcontentloaded")
            wait_for_session(context, path, url=url, timeout_s=timeout_s, poll_s=poll_s)
        finally:
            browser.close()
