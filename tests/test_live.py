"""Checks against the real site. Run with: pytest -m live

These contact Tijori, so they never run in CI. They assert accounting
identities and behaviour rather than figures, so no Tijori data sits in this
repository. Results come from a real headless browser with no signed-in session.
"""

import asyncio

import pytest

from tearsheet.core.cache import Cache
from tearsheet.sources.tijori.client import TijoriClient
from tearsheet.sources.tijori.companies import find, find_one
from tearsheet.sources.tijori.financials import build_statement
from tearsheet.sources.tijori.screener import run_screen
from tearsheet.tools.financials import load_tables

pytestmark = pytest.mark.live

COMPANIES = ["PIXTRANS", "NGLFINE"]
TOLERANCE = 0.02


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    instance = Cache(tmp_path_factory.mktemp("live") / "cache.sqlite3")
    yield instance
    instance.close()


def run(work, tmp_path):
    async def main():
        client = TijoriClient(tmp_path / "no-session.json")
        try:
            return await work(client)
        finally:
            await client.close()

    return asyncio.run(main())


def tables_for(symbol, cache, tmp_path):
    async def work(client):
        match = await find_one(client, cache, symbol)
        return (await load_tables(client, cache, match.company.slug))[0]

    return run(work, tmp_path)


def by_name(statement, name):
    return next(row for row in statement.rows if row.name == name)


@pytest.mark.parametrize("symbol", COMPANIES)
def test_symbols_resolve_exactly(symbol, cache, tmp_path):
    async def work(client):
        return await find(client, cache, symbol)

    matches = run(work, tmp_path)
    assert len(matches) == 1
    assert matches[0].matched_on == "nse_symbol"
    assert matches[0].company.bse


def test_a_name_written_like_a_symbol_still_resolves(cache, tmp_path):
    async def work(client):
        return await find(client, cache, "NGLFINECHEM")

    matches = run(work, tmp_path)
    assert [m.company.nse for m in matches] == ["NGLFINE"]
    assert matches[0].matched_on == "name"


@pytest.mark.parametrize("symbol", COMPANIES)
@pytest.mark.parametrize("basis", ["consolidated", "standalone"])
def test_ttm_is_the_sum_of_the_four_quarters_it_covers(symbol, basis, cache, tmp_path):
    tables = tables_for(symbol, cache, tmp_path)
    income = build_statement(tables, statement="income", basis=basis, periods=12).statement
    quarters = build_statement(tables, statement="quarterly", basis=basis, periods=12).statement
    assert income.periods[-1].startswith("TTM ")
    ttm_date = income.periods[-1].removeprefix("TTM ")
    end = quarters.periods.index(ttm_date)
    sales = by_name(quarters, "Net Sales").values[end - 3 : end + 1]
    assert sum(sales) == pytest.approx(by_name(income, "Sales").values[-1], abs=TOLERANCE)


@pytest.mark.parametrize("symbol", COMPANIES)
@pytest.mark.parametrize("basis", ["consolidated", "standalone"])
def test_the_balance_sheet_balances_in_every_period(symbol, basis, cache, tmp_path):
    tables = tables_for(symbol, cache, tmp_path)
    sheet = build_statement(tables, statement="balance_sheet", basis=basis, periods=12).statement
    assets = by_name(sheet, "Assets").values
    liabilities = by_name(sheet, "Liabilities").values
    assert None not in assets
    assert assets == pytest.approx(liabilities, abs=TOLERANCE)


@pytest.mark.parametrize("symbol", COMPANIES)
@pytest.mark.parametrize(
    "statement", ["income", "balance_sheet", "cash_flow", "quarterly", "ratios"]
)
def test_no_section_header_is_reported_as_a_row_of_zeros(symbol, statement, cache, tmp_path):
    tables = tables_for(symbol, cache, tmp_path)
    rows = build_statement(tables, statement=statement, periods=12).statement.rows
    headers = [r.name for r in rows if r.name.endswith("Ratios") and not any(r.values)]
    assert headers == []
    assert rows


@pytest.mark.parametrize("symbol", COMPANIES)
@pytest.mark.parametrize("basis", ["consolidated", "standalone"])
def test_no_quarter_reports_zero_profit_beside_real_profit_after_tax(
    symbol, basis, cache, tmp_path
):
    tables = tables_for(symbol, cache, tmp_path)
    quarters = build_statement(tables, statement="quarterly", basis=basis, periods=12).statement
    net = by_name(quarters, "Net Profit").values
    after_tax = by_name(quarters, "Profit After Tax").values
    assert [i for i, (n, a) in enumerate(zip(net, after_tax, strict=True)) if n == 0 and a] == []


@pytest.mark.parametrize("symbol", COMPANIES)
def test_ratio_rows_all_have_a_known_unit(symbol, cache, tmp_path):
    tables = tables_for(symbol, cache, tmp_path)
    rows = build_statement(tables, statement="ratios", detail="full").statement.rows
    assert [r.name for r in rows if r.unit == "as_reported"] == []


def test_a_business_filter_really_narrows_the_results(tmp_path):
    async def work(client):
        base = "Market Capitalization > 100000"
        wide = await run_screen(client, financial=base)
        narrow = await run_screen(client, financial=base, alternate="makes Steel")
        return len(wide), len(narrow)

    wide, narrow = run(work, tmp_path)
    assert 0 < narrow < wide
