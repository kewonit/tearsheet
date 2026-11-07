"""Screening, catalogue and market data with a fake Tijori. All data is made up."""

import asyncio
import json
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from tearsheet.core.cache import Cache
from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.sources.tijori.catalogue import Field, check_query, search_fields
from tearsheet.sources.tijori.client import Response
from tearsheet.tools import screening

CATALOGUE = [
    {"value": "Market Capitalization", "unit": "Cr", "timeperiod": "val"},
    {"value": "ROCE", "unit": "%", "timeperiod": "val"},
    {"value": "3yr Avg ROCE", "unit": "%", "timeperiod": "3yr"},
    {"value": "Net Sales", "unit": "Cr", "timeperiod": "val"},
    {"value": "3Yrs ago Net Sales", "unit": "Cr", "timeperiod": "ago"},
    {"value": "Cash & Bank Balances", "unit": "Cr", "timeperiod": "val"},
]
FIELDS = [Field(name=c["value"], unit="x", period="y") for c in CATALOGUE]
PRESETS = {
    "Value": [
        {
            "id": 7,
            "name": "Cheap Stocks",
            "plan_tier": "free",
            "financial_query": "ROCE > 1",
            "alt_query": "",
            "whales": False,
            "description": "x",
        },
        {
            "id": 8,
            "name": "Monopolies",
            "plan_tier": "premium",
            "financial_query": "",
            "alt_query": "market share > 50",
            "whales": False,
            "description": "y",
        },
    ]
}
ROWS = [
    {
        "name": f"Co {i}",
        "slug": f"co-{i}",
        "scripcode": 500000 + i,
        "nse symbol": f"CO{i}",
        "segment": "x",
        "Market Capitalization Cr": float(i),
        "<span>ROCE</span> %": 10.0 + i,
    }
    for i in range(1, 8)
]


class FakeClient:
    def __init__(self, rows=ROWS, error=None):
        self.rows, self.error = rows, error
        self.paths = []

    async def get(self, path):
        self.paths.append(path)
        query = parse_qs(urlparse(path).query, keep_blank_values=True)
        if "filter_field_search" in path:
            return Response(200, json.dumps({"data": CATALOGUE}))
        if path.endswith("popular-query/"):
            return Response(200, json.dumps(PRESETS))
        if self.error:
            return Response(500, json.dumps({"error": self.error}))
        body = {
            "data": self.rows,
            "financial_q": query["financial"][0],
            "alternate_q": query["alternate"][0],
        }
        return Response(200, json.dumps(body))


@pytest.fixture
def cache(tmp_path):
    instance = Cache(tmp_path / "cache.sqlite3")
    yield instance
    instance.close()


def call(cache, tool, client=None, **arguments):
    server = MCPServer("test")
    client = client or FakeClient()
    screening.register(server, client=client, cache=cache, read_only=None)
    try:
        result = asyncio.run(server.call_tool(tool, arguments))
    except ToolError as exc:
        return json.loads(str(exc).split(": ", 1)[1]), client.paths
    return result.structured_content, client.paths


def test_a_query_naming_real_fields_passes():
    check_query(
        "Market Capitalization > 1000 AND roce > 20% OR Net Sales > 3Yrs ago Net Sales", FIELDS
    )
    check_query(
        "(Net Sales - Market Capitalization) * 2 >= -5.5 AND Cash & Bank Balances > 0", FIELDS
    )


def test_an_unknown_field_is_named_with_suggestions():
    with pytest.raises(TearsheetError) as caught:
        check_query("Market Cap > 5 AND Reeco > 1", FIELDS)
    assert caught.value.code is ErrorCode.INVALID_INPUT
    assert "'Market Cap'" in caught.value.message
    assert "Market Capitalization" in caught.value.hint


def test_field_search_needs_every_word_and_prefers_short_names():
    assert [f.name for f in search_fields(FIELDS, "roce", 5)] == ["ROCE", "3yr Avg ROCE"]
    assert [f.name for f in search_fields(FIELDS, "avg roce", 5)] == ["3yr Avg ROCE"]
    assert [f.name for f in search_fields(FIELDS, "net slaes", 5)] == ["Net Sales"]


def test_field_search_tool_returns_units(cache):
    result, _ = call(cache, "search_screen_fields", query="roce")
    assert result["data"]["fields"][0] == {"name": "ROCE", "unit": "percent", "period": "latest"}


def test_field_search_lists_presets_and_marks_paid_ones(cache):
    result, _ = call(cache, "search_screen_fields", query="presets")
    assert [(f["name"], f["period"]) for f in result["data"]["fields"]] == [
        ("Cheap Stocks", "Value"),
        ("Monopolies", "Value, paid plan"),
    ]


def test_an_unknown_field_never_reaches_tijori(cache):
    result, paths = call(cache, "screen_stocks", financial="Made Up > 1")
    assert result["code"] == "INVALID_INPUT"
    assert not [p for p in paths if "advanced_search" in p]


def test_screens_return_units_identifiers_and_pages(cache):
    result, _ = call(cache, "screen_stocks", financial="ROCE > 1", limit=3)
    data = result["data"]
    assert data["total"] == 7
    assert [c["unit"] for c in data["columns"]] == ["crore", "percent"]
    assert data["columns"][1]["name"] == "ROCE %"
    assert (data["rows"][0]["nse"], data["rows"][0]["bse"]) == ("CO1", "500001")
    assert result["next_cursor"] == "3"


def test_paging_reuses_the_cached_screen(cache):
    client = FakeClient()
    call(cache, "screen_stocks", client=client, financial="ROCE > 1", limit=3)
    result, _ = call(
        cache, "screen_stocks", client=client, financial="ROCE > 1", limit=3, cursor="6"
    )
    assert [r["name"] for r in result["data"]["rows"]] == ["Co 7"]
    assert "next_cursor" not in result
    assert len([p for p in client.paths if "advanced_search" in p]) == 1


def test_sorting_puts_blanks_last(cache):
    rows = [dict(ROWS[0], **{"Market Capitalization Cr": None}), ROWS[1], ROWS[2]]
    result, _ = call(
        cache,
        "screen_stocks",
        client=FakeClient(rows),
        financial="ROCE > 1",
        sort_by="Market Capitalization Cr",
    )
    assert [r["name"] for r in result["data"]["rows"]] == ["Co 3", "Co 2", "Co 1"]


def test_sorting_by_an_unknown_column_lists_the_columns(cache):
    result, _ = call(cache, "screen_stocks", financial="ROCE > 1", sort_by="Nope")
    assert "ROCE %" in result["hint"]


def test_a_free_preset_runs_through_the_preset_endpoint(cache):
    result, paths = call(cache, "screen_stocks", preset="cheap")
    sent = [p for p in paths if "popular-query/results" in p][0]
    assert parse_qs(urlparse(sent).query)["query_id"] == ["7"]
    assert result["data"]["query"] == "Cheap Stocks"


def test_a_paid_preset_is_refused_on_a_free_plan_without_running_it(cache, monkeypatch, tmp_path):
    monkeypatch.setenv("TEARSHEET_HOME", str(tmp_path))
    result, paths = call(cache, "screen_stocks", preset="Monopolies")
    assert result["code"] == "PLAN_REQUIRED"
    assert not [p for p in paths if "results" in p]


def test_a_broken_tijori_preset_is_blamed_on_tijori_and_not_retried(cache):
    result, _ = call(
        cache, "screen_stocks", client=FakeClient(error="unknown word: x"), preset="Cheap"
    )
    assert result["code"] == "UPSTREAM_CHANGED"
    assert result["retryable"] is False
    assert "unknown word: x" in result["message"]


@pytest.mark.parametrize(
    "arguments",
    [{}, {"preset": "Cheap", "financial": "ROCE > 1"}, {"preset": "Value"}],
)
def test_unclear_requests_explain_themselves(cache, arguments):
    result, _ = call(cache, "screen_stocks", **arguments)
    assert result["code"] == "INVALID_INPUT"


def test_field_names_containing_and_or_are_not_split():
    fields = [
        *FIELDS,
        Field(name="Depreciation and Amortization", unit="x", period="y"),
        Field(name="Research or Development", unit="x", period="y"),
    ]
    check_query(
        "Depreciation and Amortization > 0 AND Research or Development < 5 or ROCE > 1", fields
    )
    with pytest.raises(TearsheetError):
        check_query("Depreciation > 0", fields)


def test_a_longer_field_name_wins_over_a_shorter_one_inside_it():
    fields = [*FIELDS, Field(name="Net Sales Growth", unit="x", period="y")]
    check_query("Net Sales Growth > 5", fields)
    with pytest.raises(TearsheetError):
        check_query("Net Sales Grow > 5", fields)


def test_blanks_sort_last_in_ascending_order_too(cache):
    rows = [dict(ROWS[0], **{"Market Capitalization Cr": None}), ROWS[1], ROWS[2]]
    result, _ = call(
        cache,
        "screen_stocks",
        client=FakeClient(rows),
        financial="ROCE > 1",
        sort_by="Market Capitalization Cr",
        descending=False,
    )
    assert [r["name"] for r in result["data"]["rows"]] == ["Co 2", "Co 3", "Co 1"]
