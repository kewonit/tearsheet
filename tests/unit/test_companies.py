"""All companies here are made up."""

import asyncio
import json

import pytest

from tearsheet.core.cache import Cache
from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.sources.tijori.client import Response
from tearsheet.sources.tijori.companies import (
    Company,
    Match,
    find,
    find_one,
    load_index,
    resolve,
)
from tearsheet.tools.companies import build_search

ACME = Company(name="Acme Fine-Chem", slug="acme-finechem-limited", nse="ACMEFINE", bse="500001")
ACORN = Company(name="Acorn Foods", slug="acorn-foods-limited", nse="ACORN", bse="500002")
ACORN_TWO = Company(name="Acorn Foods Two", slug="acorn-foods-two-limited", nse="ACORN2")
INDEX = [ACME, ACORN, ACORN_TWO]


def names(matches):
    return [m.company.name for m in matches]


@pytest.fixture
def cache(tmp_path):
    instance = Cache(tmp_path / "cache.sqlite3")
    yield instance
    instance.close()


class FakeClient:
    def __init__(self, search=(), main=(), sme=()):
        self.search, self.main, self.sme = search, main, sme
        self.paths = []

    async def get(self, path):
        self.paths.append(path)
        if "company_search" in path:
            return Response(200, json.dumps(list(self.search)))
        rows = self.sme if "is_sme=True" in path else self.main
        body = {"data": list(rows), "financial_q": "Market Capitalization > 0", "alternate_q": ""}
        return Response(200, json.dumps(body))


def screen_row(name="Acme Fine-Chem", slug="acme-finechem-limited", code=500001, symbol="ACMEFINE"):
    return {"name": name, "slug": slug, "scripcode": code, "nse symbol": symbol, "segment": "x"}


def test_exact_symbol_ignores_case_and_spaces():
    assert names(resolve(" acmefine ", INDEX)) == ["Acme Fine-Chem"]
    assert resolve("ACMEFINE", INDEX)[0].matched_on == "nse_symbol"


def test_bse_code():
    match = resolve("500002", INDEX)[0]
    assert (match.company.name, match.matched_on) == ("Acorn Foods", "bse_code")


def test_slug():
    assert resolve("acorn-foods-limited", INDEX)[0].matched_on == "slug"


def test_a_symbol_like_name_matches_the_name_despite_punctuation():
    match = resolve("ACMEFINECHEM", INDEX)[0]
    assert (match.company.name, match.matched_on) == ("Acme Fine-Chem", "name")


def test_an_exact_name_beats_longer_names_that_start_the_same():
    assert names(resolve("Acorn Foods Ltd", INDEX)) == ["Acorn Foods"]


def test_part_of_a_name_can_match_several():
    assert names(resolve("Acorn Fo", INDEX)) == ["Acorn Foods", "Acorn Foods Two"]


def test_an_exact_symbol_wins_over_a_name_match():
    other = Company(name="ACORN Holdings", slug="acorn-holdings", nse="ACH")
    assert names(resolve("ACORN", [other, ACORN])) == ["Acorn Foods"]


def test_duplicate_symbols_return_every_company():
    twin = Company(name="Acme Twin", slug="acme-twin", nse="ACMEFINE")
    assert len(resolve("ACMEFINE", [ACME, twin])) == 2


@pytest.mark.parametrize("query", ["", "  ", "ac", "zzzz", "99999"])
def test_unmatched_or_too_short_queries_find_nothing(query):
    assert resolve(query, INDEX) == []


def test_index_is_built_from_both_markets_and_cached(cache):
    client = FakeClient(
        main=[screen_row()],
        sme=[screen_row("Tiny", "tiny-limited", None, "TINY")],
    )
    first = asyncio.run(load_index(client, cache))
    assert [(c.name, c.market, c.bse) for c in first] == [
        ("Acme Fine-Chem", "main", "500001"),
        ("Tiny", "sme", None),
    ]
    requests = len(client.paths)
    assert asyncio.run(load_index(client, cache)) == first
    assert len(client.paths) == requests == 2


def test_a_company_in_both_markets_appears_once_as_main_board(cache):
    row = screen_row()
    companies = asyncio.run(load_index(FakeClient(main=[row], sme=[row]), cache))
    assert [(c.slug, c.market) for c in companies] == [("acme-finechem-limited", "main")]


@pytest.mark.parametrize("query", ["", "   "])
def test_a_blank_query_finds_nothing_without_asking_tijori(cache, query):
    client = FakeClient(
        main=[screen_row()], search=[{"name": "x", "slug": "x", "type": "companies"}]
    )
    assert asyncio.run(find(client, cache, query)) == []
    assert client.paths == []


def test_an_empty_index_is_a_changed_site_and_is_not_cached(cache):
    with pytest.raises(TearsheetError) as caught:
        asyncio.run(load_index(FakeClient(), cache))
    assert caught.value.code is ErrorCode.UPSTREAM_CHANGED
    assert cache.get("companies", "index") is None


def test_rows_missing_a_field_are_a_changed_site(cache):
    with pytest.raises(TearsheetError) as caught:
        asyncio.run(load_index(FakeClient(main=[{"name": "No Slug"}]), cache))
    assert caught.value.code is ErrorCode.UPSTREAM_CHANGED


def test_falls_back_to_tijori_search_keeping_identifiers_and_real_companies_only(cache):
    client = FakeClient(
        main=[screen_row()],
        search=[
            {"name": "Acme", "slug": "acme-finechem-limited", "type": "companies"},
            {"name": "Unindexed Co", "slug": "unindexed", "type": "companies"},
            {"name": "A Brand", "slug": "a-brand", "type": "brands"},
            {"name": "Old Co", "slug": "old", "type": "InActive"},
        ],
    )
    matches = asyncio.run(find(client, cache, "something else"))
    assert [(m.company.name, m.company.nse, m.matched_on) for m in matches] == [
        ("Acme Fine-Chem", "ACMEFINE", "search"),
        ("Unindexed Co", None, "search"),
    ]


def test_find_one_returns_a_single_match(cache):
    client = FakeClient(main=[screen_row()])
    assert asyncio.run(find_one(client, cache, "ACMEFINE")).company.nse == "ACMEFINE"


def test_find_one_reports_nothing_found(cache):
    with pytest.raises(TearsheetError) as caught:
        asyncio.run(find_one(FakeClient(main=[screen_row()]), cache, "zzzz"))
    assert caught.value.code is ErrorCode.NOT_FOUND


def test_find_one_lists_the_options_when_ambiguous(cache):
    rows = [
        screen_row("Acme One", "acme-one", 1, "ONE"),
        screen_row("Acme Two", "acme-two", 2, "TWO"),
    ]
    with pytest.raises(TearsheetError) as caught:
        asyncio.run(find_one(FakeClient(main=rows), cache, "Acme"))
    assert caught.value.code is ErrorCode.INVALID_INPUT
    assert "ONE" in caught.value.message and "TWO" in caught.value.message


def test_a_wrong_symbol_gets_a_warning_naming_the_real_one():
    result = build_search("ACMEFINECHEM", [Match(ACME, "name")])
    assert result.warnings == [
        "'ACMEFINECHEM' isn't an NSE symbol, so this matched on the name. "
        "The NSE symbol is ACMEFINE."
    ]
    assert result.entity.nse == "ACMEFINE"


def test_a_plain_name_search_gets_no_symbol_warning():
    assert build_search("Acme Fine", [Match(ACME, "name")]).warnings == []


def test_several_matches_set_no_entity():
    result = build_search("Acorn", [Match(ACORN, "name"), Match(ACORN_TWO, "name")])
    assert result.entity is None
    assert len(result.data.matches) == 2


def test_no_matches_is_a_normal_result_with_a_note():
    result = build_search("zzzz", [])
    assert result.data.matches == []
    assert "Nothing matched" in result.warnings[0]
