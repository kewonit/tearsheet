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


@pytest.mark.parametrize("symbol", COMPANIES)
@pytest.mark.parametrize("basis", ["consolidated", "standalone"])
def test_cash_flows_add_up_in_every_period(symbol, basis, cache, tmp_path):
    tables = tables_for(symbol, cache, tmp_path)
    flows = build_statement(tables, statement="cash_flow", basis=basis, periods=12).statement
    parts = zip(
        by_name(flows, "Cash from Operating Activity").values,
        by_name(flows, "Cash from Investing Activity").values,
        by_name(flows, "Cash from Financing Activity").values,
        strict=True,
    )
    # A blank means no such activity was reported that year, so it adds nothing.
    assert [sum(value or 0 for value in part) for part in parts] == pytest.approx(
        by_name(flows, "Net Cash Flow").values, abs=TOLERANCE
    )


def test_bank_rows_keep_honest_units(cache, tmp_path):
    tables = tables_for("HDFCBANK", cache, tmp_path)
    rows = build_statement(tables, statement="quarterly", detail="full").statement.rows
    units = {row.name: row.unit for row in rows}
    assert units["General and Administration Expenses"] == "crore"
    assert units["Gross NPA"] == "as_reported"
    assert units["CASA Ratio"] == "as_reported"


def test_an_off_year_end_cash_flow_column_is_labelled_interim(cache, tmp_path):
    tables = tables_for("TCS", cache, tmp_path)
    parsed = build_statement(tables, statement="cash_flow")
    assert parsed.statement.periods[-1].startswith("Interim ")
    assert parsed.warnings


def test_no_symbol_is_ambiguous_because_a_company_moved_markets(cache, tmp_path):
    async def work(client):
        return await find(client, cache, "GCMCOMM")

    assert len(run(work, tmp_path)) == 1


def page_data(symbol, cache, tmp_path):
    from tearsheet.tools.company import load_company

    async def work(client):
        match = await find_one(client, cache, symbol)
        return (await load_company(client, cache, match.company.slug))[0]

    return run(work, tmp_path)


@pytest.mark.parametrize("symbol", COMPANIES)
def test_market_cap_is_price_times_shares(symbol, cache, tmp_path):
    data = page_data(symbol, cache, tmp_path)
    tables = tables_for(symbol, cache, tmp_path)
    income = build_statement(tables, statement="income", periods=3).statement
    # A TTM column has no share count, so use the latest year that has one.
    counts = by_name(income, "Number of shares(Crs)").values
    shares_crore = next(value for value in reversed(counts) if value is not None)
    # Share counts are rounded to two decimals of a crore, hence the loose tolerance.
    assert data.page.price * shares_crore == pytest.approx(data.page.market_cap_crore, rel=0.05)


@pytest.mark.parametrize("symbol", [*COMPANIES, "HDFCBANK", "LICI"])
def test_ownership_adds_up_to_one_hundred_percent(symbol, cache, tmp_path):
    from tearsheet.sources.tijori.ownership import parse_shareholding

    async def work(client):
        match = await find_one(client, cache, symbol)
        return (await client.get(f"/company/{match.company.slug}/shareholding/")).text

    ownership = parse_shareholding(run(work, tmp_path), full=False, periods=4)
    top = [row for row in ownership.rows if row.level == 1 and row.unit == "percent"]
    for index in range(len(ownership.periods)):
        assert sum(row.values[index] or 0 for row in top) == pytest.approx(100, abs=0.1)


@pytest.mark.parametrize("symbol", [*COMPANIES, "HDFCBANK", "TCS"])
def test_every_revenue_split_adds_up_to_one_hundred_percent(symbol, cache, tmp_path):
    for chart in page_data(symbol, cache, tmp_path).revenue_mix:
        assert sum(f.value or 0 for f in chart.latest) == pytest.approx(100, abs=1)


def test_an_anonymous_session_has_no_paid_features(cache, tmp_path):
    entitlements = page_data("NGLFINE", cache, tmp_path).page.entitlements
    assert (entitlements.plan_tier, entitlements.metrics_history) == ("free", False)
    assert (entitlements.revenue_mix_history, entitlements.market_share_history) == (False, False)


def test_fund_flow_parts_add_up_to_their_totals(cache, tmp_path):
    from tearsheet.tools.financials import _fund_flow

    async def work(client):
        match = await find_one(client, cache, "NGLFINE")
        return await _fund_flow(client, cache, match.company.slug, 5)

    statement = run(work, tmp_path)[0].statement
    for group in ("Sources of funds", "Uses of funds"):
        rows = [r for r in statement.rows if r.group == group]
        total = next(r for r in rows if r.name.startswith("Total"))
        for index in range(len(statement.periods)):
            parts = sum(r.values[index] or 0 for r in rows if r is not total)
            assert parts == pytest.approx(total.values[index], abs=0.1)


def test_sector_weights_add_up_to_one_hundred_percent(tmp_path):
    from tearsheet.sources.tijori.markets import load_constituents, parse_markets

    async def work(client):
        tables = parse_markets((await client.get("/in/markets")).text)
        sector = tables["sectors"].rows[0]
        return await load_constituents(client, "sectors", sector.market_id)

    weights = [c.weight_percent for c in run(work, tmp_path)]
    assert sum(weights) == pytest.approx(100, abs=1)


def test_every_catalogue_field_is_accepted_by_the_query_check(cache, tmp_path):
    from tearsheet.sources.tijori.catalogue import check_query, load_catalogue

    async def work(client):
        return await load_catalogue(client, cache)

    fields = run(work, tmp_path)
    for field in fields:
        check_query(f"{field.name} > 0", fields)
