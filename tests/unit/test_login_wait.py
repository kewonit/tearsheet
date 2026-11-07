"""Failure paths of wait_for_session that need no browser."""

import pytest
from playwright.sync_api import Error as PlaywrightError

from tearsheet.login import LoginCancelledError, wait_for_session


class BrokenContext:
    """A context that still lists a tab but can no longer answer."""

    pages = ["tab"]

    def cookies(self, url):
        raise PlaywrightError("Target page, context or browser has been closed")


def test_a_browser_error_cancels_even_if_tabs_are_still_listed(tmp_path):
    path = tmp_path / "session.json"
    with pytest.raises(LoginCancelledError):
        wait_for_session(BrokenContext(), path, url="http://localhost/", timeout_s=30, poll_s=0.01)
    assert not path.exists()
