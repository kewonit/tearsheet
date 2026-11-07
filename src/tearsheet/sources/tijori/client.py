"""Requests to Tijori, made from inside a headless browser.

Tijori refuses plain HTTP clients but serves an ordinary browser, so Tearsheet
keeps one headless browser open. It doesn't disguise itself. Requests run from
/robots.txt because real pages poll for live prices, and a page left open would
keep contacting Tijori in the background.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.core.ratelimit import RateLimiter
from tearsheet.core.session import SessionState, read_session_info

BASE_URL = "https://www.tijorifinance.com"
QUIET_PAGE = "/robots.txt"
SIGN_IN_HINT = "Ask the user to run: tearsheet login"

_FETCH = """async (path) => {
    const response = await fetch(path, {credentials: 'same-origin'});
    return {status: response.status, text: await response.text()};
}"""


@dataclass(frozen=True)
class Response:
    status: int
    text: str

    def json(self) -> Any:
        """Parse the body. Tijori labels some JSON as text/html, so headers aren't trusted."""
        try:
            return json.loads(self.text)
        except ValueError as exc:
            raise TearsheetError(
                ErrorCode.UPSTREAM_CHANGED, "Tijori returned something other than JSON."
            ) from exc


def _raise_for_refusal(status: int) -> None:
    if status == 401:
        raise TearsheetError(
            ErrorCode.SESSION_EXPIRED, "Tijori needs a sign-in.", hint=SIGN_IN_HINT
        )
    if status == 403:
        raise TearsheetError(
            ErrorCode.BLOCKED,
            "Tijori refused the request, so Tearsheet has stopped.",
            hint="Don't retry. Tell the user Tijori refused access.",
        )
    if status == 429:
        raise TearsheetError(ErrorCode.RATE_LIMITED, "Tijori asked Tearsheet to slow down.")
    if status in (502, 503, 504):
        raise TearsheetError(ErrorCode.UPSTREAM_UNAVAILABLE, f"Tijori returned {status}.")


class TijoriClient:
    """A single rate-limited browser session. Start-up is lazy, so offline tools stay fast."""

    def __init__(
        self,
        session_file: Path,
        *,
        base_url: str = BASE_URL,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._session_file = session_file
        self._base_url = base_url
        self._limiter = limiter or RateLimiter()
        self._start_lock = asyncio.Lock()
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    async def _start(self) -> None:
        # Imported here so tools that never touch Tijori don't pay for Playwright.
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright

        session = read_session_info(self._session_file)
        storage_state = str(self._session_file) if session.state is SessionState.SAVED else None
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(headless=True)
            context = await self._browser.new_context(storage_state=storage_state)
            page = await context.new_page()
            response = await page.goto(
                self._base_url + QUIET_PAGE, wait_until="domcontentloaded", timeout=45_000
            )
        except PlaywrightError as exc:
            await self.close()
            if "Executable doesn't exist" in str(exc):
                raise TearsheetError(
                    ErrorCode.SETUP_REQUIRED,
                    "Chromium isn't installed.",
                    hint="Ask the user to run: playwright install chromium",
                ) from exc
            raise TearsheetError(
                ErrorCode.UPSTREAM_UNAVAILABLE, "The browser couldn't reach Tijori."
            ) from exc
        if response is not None:
            try:
                _raise_for_refusal(response.status)
            except TearsheetError:
                await self.close()
                raise
        self._page = page

    async def get(self, path: str) -> Response:
        """Fetch a path on Tijori's site, stopping at any refusal."""
        from playwright.async_api import Error as PlaywrightError

        if not path.startswith("/"):
            raise ValueError("path must start with /")
        async with self._start_lock:
            if self._page is None:
                await self._start()
            page = self._page
        async with self._limiter.slot():
            try:
                result = await page.evaluate(_FETCH, path)
            except PlaywrightError as exc:
                await self.close()
                raise TearsheetError(
                    ErrorCode.UPSTREAM_UNAVAILABLE, "The browser lost contact with Tijori."
                ) from exc
        _raise_for_refusal(result["status"])
        return Response(result["status"], result["text"])

    async def close(self) -> None:
        """Shut the browser down. Safe to call at any time, and more than once."""
        browser, playwright = self._browser, self._playwright
        self._browser = self._playwright = self._page = None
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()
