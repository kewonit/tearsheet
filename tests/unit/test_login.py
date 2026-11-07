"""Runs real headless Chromium against a local site. Run with: pytest -m browser"""

import json
import stat
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import sync_playwright

from tearsheet.login import LoginCancelledError, LoginTimeoutError, login, wait_for_session

pytestmark = pytest.mark.browser

SIGNED_IN = "<html><body>signed in</body></html>"
PAGES = {
    "/no-cookie": "<html><body>sign in here</body></html>",
    "/redirects": "<script>setTimeout(() => location = '/signed-in', 300)</script>",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        if self.path == "/signed-in":
            self.send_header("Set-Cookie", "sessionid=fake-value; Path=/")
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGES.get(self.path, SIGNED_IN).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def run(site, page, path, **kwargs):
    login(path, url=site + page, headless=True, poll_s=0.05, **kwargs)


def cookie_names(path):
    return [cookie["name"] for cookie in json.loads(path.read_text())["cookies"]]


def test_waits_for_a_redirect_that_signs_the_user_in(site, tmp_path):
    path = tmp_path / "session.json"
    run(site, "/redirects", path, timeout_s=10)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert cookie_names(path) == ["sessionid"]


@pytest.fixture
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def wait(context, site, path, timeout_s=5):
    wait_for_session(context, path, url=site, timeout_s=timeout_s, poll_s=0.05)


def test_keeps_waiting_when_one_tab_closes_and_another_signs_in(site, browser, tmp_path):
    path = tmp_path / "session.json"
    context = browser.new_context()
    first, second = context.new_page(), context.new_page()
    first.goto(site + "/no-cookie")
    second.goto(site + "/redirects")
    first.close()
    wait(context, site, path)
    assert cookie_names(path) == ["sessionid"]


def test_closing_every_tab_cancels_straight_away(site, browser, tmp_path):
    path = tmp_path / "session.json"
    context = browser.new_context()
    context.new_page().close()
    started = time.monotonic()
    with pytest.raises(LoginCancelledError):
        wait(context, site, path, timeout_s=30)
    assert time.monotonic() - started < 5
    assert not path.exists()


def test_the_browser_going_away_cancels_straight_away(site, tmp_path):
    path = tmp_path / "session.json"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.new_page()
        browser.close()
        started = time.monotonic()
        with pytest.raises(LoginCancelledError):
            wait(context, site, path, timeout_s=30)
        assert time.monotonic() - started < 5
        browser.close()
    assert not path.exists()


def test_times_out_without_saving_anything(site, tmp_path):
    path = tmp_path / "session.json"
    with pytest.raises(LoginTimeoutError):
        run(site, "/no-cookie", path, timeout_s=0.3)
    assert not path.exists()
