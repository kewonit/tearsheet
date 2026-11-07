"""Runs real headless Chromium against a local page. Run with: pytest -m browser"""

import json
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tearsheet.login import LoginTimeoutError, login

pytestmark = pytest.mark.browser


def serve(set_cookie: bool):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            if set_cookie:
                self.send_header("Set-Cookie", "sessionid=fake-value; Path=/")
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>test</body></html>")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_saves_the_session_once_the_cookie_appears(tmp_path):
    server = serve(set_cookie=True)
    path = tmp_path / "session.json"
    try:
        login(path, url=f"http://127.0.0.1:{server.server_port}/", headless=True, poll_ms=50)
    finally:
        server.shutdown()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [c["name"] for c in json.loads(path.read_text())["cookies"]] == ["sessionid"]


def test_times_out_without_saving_anything(tmp_path):
    server = serve(set_cookie=False)
    path = tmp_path / "session.json"
    try:
        with pytest.raises(LoginTimeoutError):
            login(
                path,
                url=f"http://127.0.0.1:{server.server_port}/",
                headless=True,
                timeout_s=0.3,
                poll_ms=50,
            )
    finally:
        server.shutdown()
    assert not path.exists()
