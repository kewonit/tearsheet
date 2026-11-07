"""Runs the real client in headless Chromium against a local site. Run with: pytest -m browser"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.core.ratelimit import RateLimiter
from tearsheet.sources.tijori.client import TijoriClient

pytestmark = pytest.mark.browser

ROUTES = {
    "/robots.txt": (200, "text/plain", "User-agent: *"),
    "/json-labelled-html": (200, "text/html", '[{"name": "Example"}]'),
    "/page": (200, "text/html", "<html>not json</html>"),
    "/missing": (404, "text/html", "nope"),
    "/unauthorised": (401, "text/plain", "x"),
    "/forbidden": (403, "text/plain", "x"),
    "/slow-down": (429, "text/plain", "x"),
    "/down": (503, "text/plain", "x"),
}


class Handler(BaseHTTPRequestHandler):
    requests: list[str] = []

    def do_GET(self):
        Handler.requests.append(self.path)
        status, content_type, body = ROUTES.get(self.path, (404, "text/plain", "x"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    Handler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def run(site, tmp_path, work):
    async def main():
        client = TijoriClient(
            tmp_path / "none.json", base_url=site, limiter=RateLimiter(min_interval_s=0)
        )
        try:
            return await work(client)
        finally:
            await client.close()

    return asyncio.run(main())


def test_reads_json_by_its_body_even_when_labelled_html(site, tmp_path):
    async def work(client):
        return (await client.get("/json-labelled-html")).json()

    assert run(site, tmp_path, work) == [{"name": "Example"}]


def test_a_non_json_body_is_reported_as_a_changed_site(site, tmp_path):
    async def work(client):
        (await client.get("/page")).json()

    with pytest.raises(TearsheetError) as caught:
        run(site, tmp_path, work)
    assert caught.value.code is ErrorCode.UPSTREAM_CHANGED


def test_other_statuses_are_left_to_the_caller(site, tmp_path):
    async def work(client):
        return (await client.get("/missing")).status

    assert run(site, tmp_path, work) == 404


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("/unauthorised", ErrorCode.SESSION_EXPIRED),
        ("/forbidden", ErrorCode.BLOCKED),
        ("/slow-down", ErrorCode.RATE_LIMITED),
        ("/down", ErrorCode.UPSTREAM_UNAVAILABLE),
    ],
)
def test_refusals_become_errors_the_agent_can_act_on(site, tmp_path, path, code):
    async def work(client):
        await client.get(path)

    with pytest.raises(TearsheetError) as caught:
        run(site, tmp_path, work)
    assert caught.value.code is code


def test_a_block_is_not_retried(site, tmp_path):
    async def work(client):
        await client.get("/forbidden")

    with pytest.raises(TearsheetError):
        run(site, tmp_path, work)
    assert Handler.requests.count("/forbidden") == 1


def test_one_browser_serves_many_requests_and_never_leaves_the_quiet_page(site, tmp_path):
    async def work(client):
        for _ in range(3):
            await client.get("/json-labelled-html")

    run(site, tmp_path, work)
    assert Handler.requests.count("/robots.txt") == 1
    assert Handler.requests.count("/json-labelled-html") == 3


def test_close_is_safe_twice_and_the_client_can_start_again(site, tmp_path):
    async def work(client):
        await client.get("/json-labelled-html")
        await client.close()
        await client.close()
        return (await client.get("/json-labelled-html")).status

    assert run(site, tmp_path, work) == 200


def test_rejects_a_path_that_could_leave_the_site(site, tmp_path):
    async def work(client):
        await client.get("https://example.com/")

    with pytest.raises(ValueError):
        run(site, tmp_path, work)


def test_several_callers_share_one_browser_start(site, tmp_path):
    async def work(client):
        await asyncio.gather(*(client.get("/json-labelled-html") for _ in range(4)))

    run(site, tmp_path, work)
    assert Handler.requests.count("/robots.txt") == 1


def test_cancelling_a_caller_during_start_up_does_not_stop_a_clean_close(site, tmp_path):
    async def work(client):
        task = asyncio.create_task(client.get("/json-labelled-html"))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(client.close(), timeout=20)
        return client._browser, client._page

    assert run(site, tmp_path, work) == (None, None)
