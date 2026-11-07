"""Tool behaviour with a fake Tijori. All data here is made up."""

import asyncio
import json

import pytest
from mcp.server.mcpserver import MCPServer

from tearsheet.core.cache import Cache
from tearsheet.sources.tijori.client import Response
from tearsheet.tools import company as company_tools
from tests.unit.test_company_page import block, page

METRICS = (
    '<li metricid="11" indent="0" unit="kL" title="Capacity"></li>'
    '<li metricid="12" indent="0" unit="%" title="Utilisation"></li>'
)
MIX = """<div class="rmix_graph_block"><h4>Product</h4>
<div class="rmix_pie_chart" chart-id="9" chart-data="[[&quot;Widgets&quot;, 100.0]]"></div></div>"""
POINTS = {"data": [[1711909800000, 10.0], [1743445800000, 20.0], [1774981800000, 30.0]]}


class FakeClient:
    def __init__(self, html):
        self.html = html
        self.paths = []

    async def get(self, path):
        self.paths.append(path)
        if "advanced_search" in path:
            rows = [{"name": "Acme", "slug": "acme", "scripcode": 500001, "nse symbol": "ACMEFINE"}]
            body = {
                "data": rows if "is_sme=False" in path else [],
                "financial_q": "Market Capitalization > 0",
            }
            return Response(200, json.dumps(body))
        if "company_op_metrics" in path:
            return Response(200, json.dumps(POINTS))
        if "rmix/historic" in path:
            graph = json.dumps([[1774981800000, 100.0]])
            return Response(
                200, json.dumps({"context": [{"fieldname": "Widgets", "graphdata": graph}]})
            )
        return Response(200, self.html)


@pytest.fixture
def cache(tmp_path):
    instance = Cache(tmp_path / "cache.sqlite3")
    yield instance
    instance.close()


def call(html, cache, tool, **arguments):
    server = MCPServer("test")
    client = FakeClient(html)
    company_tools.register(server, client=client, cache=cache, read_only=None)
    result = asyncio.run(server.call_tool(tool, {"company": "ACMEFINE", **arguments}))
    return result.structured_content, client.paths


FREE = page(extra=METRICS + MIX)
PAID = page(
    locks={"op_metrics": {"historic": True}, "rev_mix": {"historic": True}},
    plan={"plan_tier": "premium", "ind_company": {"overview": {"rev_mix": {"historic": True}}}},
    extra=METRICS + MIX,
)


def test_free_plan_gets_only_the_latest_metric_value(cache):
    result, _ = call(FREE, cache, "get_operating_metrics")
    metric = result["data"]["metrics"][0]
    assert (metric["latest_date"], metric["latest_value"], metric["history"]) == (
        "2026-04-01",
        30.0,
        None,
    )
    assert "paid Tijori plan" in result["warnings"][0]


def test_free_plan_history_is_not_even_cached(cache):
    call(FREE, cache, "get_operating_metrics")
    stored = [cache.get("operating_metrics", f"77:{m}:latest").value for m in ("11", "12")]
    assert all(len(points) == 1 for points in stored)
    assert cache.get("operating_metrics", "77:11:all") is None


def test_paid_plan_gets_history(cache):
    result, _ = call(PAID, cache, "get_operating_metrics")
    assert len(result["data"]["metrics"][0]["history"]) == 3
    assert result["data"]["history_included"] is True


def test_free_plan_never_requests_revenue_mix_history(cache):
    result, paths = call(FREE, cache, "get_business_mix")
    assert not [p for p in paths if "rmix/historic" in p]
    assert result["data"]["revenue_mix_history"] is None
    assert result["data"]["revenue_mix"][0]["latest"][0]["value"] == 100.0


def test_paid_plan_requests_revenue_mix_history(cache):
    result, paths = call(PAID, cache, "get_business_mix")
    assert [p for p in paths if "rmix/historic" in p] == ["/api/rmix/historic/graph/9"]
    assert result["data"]["revenue_mix_history"]["Product"] == [["2026-04-01", {"Widgets": 100.0}]]


def test_a_company_without_metrics_is_a_normal_empty_result(cache):
    result, paths = call(page(), cache, "get_operating_metrics")
    assert result["data"]["metrics"] == []
    assert not [p for p in paths if "company_op_metrics" in p]
    assert "no operating metrics" in result["warnings"][0]


def test_metric_filter_and_limit(cache):
    result, _ = call(FREE, cache, "get_operating_metrics", metric="util", limit=1)
    assert [m["name"] for m in result["data"]["metrics"]] == ["Utilisation"]


def test_snapshot_has_facts_and_no_opinions(cache):
    result, _ = call(FREE, cache, "company_snapshot")
    assert result["data"]["nse"] == "ACMEFINE"
    assert result["data"]["bse"] == "500001"
    assert "TIJORI OPINION" not in json.dumps(result)
    assert any("delayed" in w for w in result["warnings"])


def test_an_inactive_company_is_flagged_first(cache):
    html = FREE.replace(block("company_status", "Active"), block("company_status", "Suspended"))
    result, _ = call(html, cache, "company_snapshot")
    assert "Suspended" in result["warnings"][0]


def test_one_page_fetch_serves_several_tools(cache):
    server = MCPServer("test")
    client = FakeClient(FREE)
    company_tools.register(server, client=client, cache=cache, read_only=None)
    for tool in ("company_snapshot", "get_business_mix", "get_operating_metrics"):
        asyncio.run(server.call_tool(tool, {"company": "ACMEFINE"}))
    assert client.paths.count("/company/acme/") == 1
