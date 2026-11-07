import asyncio

import pytest
from mcp.server.mcpserver import MCPServer

from tearsheet import prompts


@pytest.fixture
def server():
    instance = MCPServer("test")
    prompts.register(instance)
    return instance


def test_three_prompts_are_offered(server):
    names = [p.name for p in asyncio.run(server.list_prompts())]
    assert names == ["earnings_review", "peer_comparison", "thesis_check"]


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("earnings_review", {"company": "ACME"}),
        ("peer_comparison", {"company": "ACME"}),
        ("thesis_check", {"company": "ACME", "thesis": "margins are rising"}),
    ],
)
def test_every_prompt_asks_for_units_and_rules_out_advice(server, name, arguments):
    result = asyncio.run(server.get_prompt(name, arguments))
    text = " ".join(m.content.text for m in result.messages)
    assert "ACME" in text
    assert "unit and period" in text
    assert "Don't recommend buying, selling or holding" in text
