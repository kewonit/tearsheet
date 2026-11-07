"""Drive the real server process over stdio with raw JSON-RPC.

This checks what a client actually receives, for clients on the current
protocol and on the 2025 revision.
"""

import json
import os
import queue
import subprocess
import sys
import threading

import jsonschema
import pytest

NEW = "2026-07-28"
OLD = "2025-11-25"
META = {
    "io.modelcontextprotocol/protocolVersion": NEW,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"},
}


class Server:
    def __init__(self, home):
        env = {**os.environ, "TEARSHEET_HOME": str(home)}
        env.pop("TEARSHEET_FILINGS_DIR", None)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "tearsheet"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.next_id = 0

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def request(self, method, params=None, *, modern=True):
        self.next_id += 1
        params = dict(params or {})
        if modern:
            params["_meta"] = META
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        reply = json.loads(self.lines.get(timeout=20))
        assert reply["id"] == self.next_id
        return reply

    def stop(self):
        if not self.process.stdin.closed:
            self.process.stdin.close()
        self.process.wait(timeout=10)


@pytest.fixture
def server(tmp_path):
    instance = Server(tmp_path)
    yield instance
    instance.stop()


def status_call(server, **kwargs):
    return server.request("tools/call", {"name": "server_status", "arguments": {}}, **kwargs)


def test_discover_reports_the_current_protocol(server):
    result = server.request("server/discover")["result"]
    assert NEW in result["supportedVersions"]
    assert result["resultType"] == "complete"
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "tearsheet"


def test_tool_list_is_stable_cacheable_and_read_only(server):
    first = server.request("tools/list")["result"]
    second = server.request("tools/list")["result"]
    assert [t["name"] for t in first["tools"]] == [
        "find_company",
        "get_financials",
        "company_snapshot",
        "get_ownership",
        "get_operating_metrics",
        "get_business_mix",
        "search_screen_fields",
        "screen_stocks",
        "compare_companies",
        "get_sector_view",
        "search_filings",
        "read_filing",
        "reconcile_figure",
        "server_status",
    ]
    assert first["tools"] == second["tools"]
    assert first["ttlMs"] == 3_600_000
    assert first["cacheScope"] == "public"
    assert all(t["annotations"]["readOnlyHint"] is True for t in first["tools"])


def test_status_result_matches_its_declared_schema(server):
    tools = server.request("tools/list")["result"]["tools"]
    tool = next(t for t in tools if t["name"] == "server_status")
    result = status_call(server)["result"]
    assert result["isError"] is False
    jsonschema.validate(result["structuredContent"], tool["outputSchema"])


def test_status_text_is_compact_and_matches_the_structured_data(server):
    result = status_call(server)["result"]
    text = result["content"][0]["text"]
    assert json.loads(text) == result["structuredContent"]
    assert "\n" not in text


def test_fresh_install_reports_no_session(server):
    data = status_call(server)["result"]["structuredContent"]
    assert data["data"]["session"] == "none"
    assert any("tearsheet login" in warning for warning in data["warnings"])


def test_unknown_tool_is_reported_without_crashing(server):
    reply = server.request("tools/call", {"name": "nope", "arguments": {}})
    assert reply.get("error") or reply["result"]["isError"] is True
    assert status_call(server)["result"]["isError"] is False


def test_older_clients_are_served(server):
    params = {
        "protocolVersion": OLD,
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    }
    init = server.request("initialize", params, modern=False)["result"]
    assert init["protocolVersion"] == OLD
    assert init["serverInfo"]["version"]
    server.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    result = status_call(server, modern=False)["result"]
    assert result["structuredContent"]["data"]["session"] == "none"


def test_stdout_carries_only_protocol_messages(server):
    status_call(server)
    server.stop()
    leftovers = []
    while not server.lines.empty():
        leftovers.append(server.lines.get())
    for line in leftovers:
        json.loads(line)
