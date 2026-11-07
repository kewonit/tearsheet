"""Market monitor parsing with a fake Tijori. All data here is made up."""

import asyncio
import json

import pytest
from mcp.server.mcpserver import MCPServer

from tearsheet.core.cache import Cache
from tearsheet.sources.tijori.client import Response
from tearsheet.sources.tijori.markets import parse_markets
from tearsheet.tools import markets as market_tools


@pytest.fixture
def cache(tmp_path):
    instance = Cache(tmp_path / "cache.sqlite3")
    yield instance
    instance.close()


MARKETS = """
<table id="market__table__headline"><tr><th></th><th>1D</th><th>1YR*</th></tr>
<tr><td>Nifty 50</td><td>1.5</td><td></td></tr></table>
<table id="market__table__niche"><tr><th></th><th>WEIGHT</th><th>1D</th></tr>
<tr tjiid="42"><td>TJI Widgets + 2 8</td><td>2 8</td><td>-0.5</td></tr></table>
<table id="market__table__groups"><tr><th></th><th>WEIGHT</th><th>Mar26</th></tr>
<tr tjiid="9"><td>Acme Group +</td><td></td><td>—</td></tr></table>
"""


def test_market_tables_are_parsed_with_their_own_columns():
    tables = parse_markets(MARKETS)
    assert tables["indices"].columns == ["1D", "1YR*"]
    assert tables["sectors"].rows[0].name == "TJI Widgets"
    assert tables["sectors"].rows[0].market_id == "42"
    assert tables["sectors"].rows[0].values == {"1D": -0.5}


class MarketClient:
    def __init__(self):
        self.paths = []

    async def get(self, path):
        self.paths.append(path)
        if path == "/in/markets":
            return Response(200, MARKETS)
        weights = ["60", "40"] if "niche" in path else ["0", "0"]
        data = [
            {"name": f"Member {i}", "slug": f"m-{i}", "weight": w} for i, w in enumerate(weights)
        ]
        return Response(200, json.dumps({"data": data}))


def sector(cache, **arguments):
    server = MCPServer("test")
    client = MarketClient()
    market_tools.register(server, client=client, cache=cache, read_only=None)
    return asyncio.run(
        server.call_tool("get_sector_view", arguments)
    ).structured_content, client.paths


def test_each_kind_uses_its_own_constituents_endpoint(cache):
    sectors, paths = sector(cache, name="widgets")
    assert paths[-1] == "/api/v1/niche/price/42/"
    assert [c["weight_percent"] for c in sectors["data"]["constituents"]] == [60.0, 40.0]
    groups, paths = sector(cache, kind="conglomerates", name="acme")
    assert paths[-1] == "/api/v1/groups/price/9/"
    assert [c["weight_percent"] for c in groups["data"]["constituents"]] == [None, None]


def test_unexplained_asterisks_are_flagged(cache):
    result, _ = sector(cache, kind="indices")
    assert "aren't explained" in result["warnings"][0]
