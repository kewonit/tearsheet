import asyncio
import json
from urllib.parse import parse_qs, urlparse

import pytest

from tearsheet.core.errors import ErrorCode, ToolFailure
from tearsheet.sources.tijori.client import Response
from tearsheet.sources.tijori.screener import run_screen


class FakeClient:
    def __init__(self, body, status=200):
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.status = status
        self.paths = []

    async def get(self, path):
        self.paths.append(path)
        return Response(self.status, self.text)


def body(**overrides):
    return {
        "data": [{"name": "Example", "<span>latest</span>Mcap<span>Cr</span>": 10}],
        "financial_q": "ROCE > 20",
        "alternate_q": "",
        **overrides,
    }


def run(client, **kwargs):
    return asyncio.run(run_screen(client, **kwargs))


def sent(client):
    return parse_qs(urlparse(client.paths[0]).query, keep_blank_values=True)


def test_returns_rows_with_html_removed_from_keys():
    assert run(FakeClient(body()), financial="ROCE > 20") == [
        {"name": "Example", "latest Mcap Cr": 10}
    ]


def test_sends_the_business_filter_under_the_name_tijori_honours():
    client = FakeClient(body(alternate_q="makes Example"))
    run(client, financial="ROCE > 20", alternate="makes Example")
    assert sent(client)["alternate"] == ["makes Example"]
    assert "aq" not in sent(client)


def test_flags_are_sent_as_tijori_expects():
    client = FakeClient(body())
    run(client, financial="ROCE > 20", latest_results_only=True, sme=True)
    assert sent(client)["is_checked"] == ["True"]
    assert sent(client)["is_sme"] == ["True"]
    assert sent(client)["whales"] == ["False"]


def test_unknown_options_cannot_be_passed():
    with pytest.raises(TypeError):
        run(FakeClient(body()), aq="makes Example")


@pytest.mark.parametrize(
    ("kwargs", "overrides"),
    [
        ({"financial": "ROCE > 20", "alternate": "makes Example"}, {"alternate_q": ""}),
        ({"financial": "ROCE > 20", "alternate": "makes Example"}, {"alternate_q": None}),
        ({"financial": "ROCE > 20"}, {"financial_q": ""}),
        ({"financial": "ROCE > 20"}, {"financial_q": "ROE > 20"}),
    ],
)
def test_refuses_results_when_a_filter_was_not_applied(kwargs, overrides):
    with pytest.raises(ToolFailure) as caught:
        run(FakeClient(body(**overrides)), **kwargs)
    assert caught.value.code is ErrorCode.UPSTREAM_CHANGED


def test_echo_comparison_ignores_spacing_and_case():
    assert run(FakeClient(body(financial_q="  roce  >  20 ")), financial="ROCE > 20")


def test_a_bad_query_explains_itself():
    with pytest.raises(ToolFailure) as caught:
        run(FakeClient({"error": "bad"}, status=500), financial="Made Up > 1")
    assert caught.value.code is ErrorCode.INVALID_INPUT
    assert "catalogue" in caught.value.hint


@pytest.mark.parametrize(
    "bad", [[], {"financial_q": "ROCE > 20"}, {"data": 5, "financial_q": "ROCE > 20"}]
)
def test_an_unexpected_shape_is_reported_as_a_changed_site(bad):
    with pytest.raises(ToolFailure) as caught:
        run(FakeClient(bad), financial="ROCE > 20")
    assert caught.value.code is ErrorCode.UPSTREAM_CHANGED
