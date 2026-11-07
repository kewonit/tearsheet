"""The compare_companies tool. All growth figures are computed here, not by the model."""

from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from tearsheet.analytics.ratios import cagr_percent, growth_percent, summary
from tearsheet.core.cache import Cache
from tearsheet.core.envelope import Envelope, Source, to_result
from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.sources.tijori.client import BASE_URL, TijoriClient
from tearsheet.sources.tijori.companies import find_one
from tearsheet.sources.tijori.financials import build_statement
from tearsheet.tools.companies import CompanyQuery
from tearsheet.tools.company import load_company
from tearsheet.tools.financials import load_tables

_REVENUE = ("Sales", "Net Sales", "Total Income")
_RATIO_PICKS = {
    "ROE": "roe_percent",
    "ROCE": "roce_percent",
    "Debt to Equity Ratio": "debt_to_equity",
    "Dividend Yield": "dividend_yield_percent",
    "Promoter": "promoter_percent",
}
METRICS = {
    "price_rupees": "rupees",
    "market_cap_crore": "crore",
    "pe": "multiple",
    "peg": "multiple",
    "roe_percent": "percent",
    "roce_percent": "percent",
    "debt_to_equity": "multiple",
    "dividend_yield_percent": "percent",
    "promoter_percent": "percent",
    "revenue_latest_year_crore": "crore",
    "revenue_growth_percent": "percent",
    "net_profit_growth_percent": "percent",
    "revenue_cagr_3y_percent": "percent",
}


class CompanyRow(BaseModel):
    name: str
    nse: str | None
    latest_year: str | None
    values: dict[str, float | None]


class Comparison(BaseModel):
    units: dict[str, str]
    companies: list[CompanyRow]
    summary: dict[str, dict[str, float | None]]


def _annual(periods: list[str], values: list[float | None]) -> list[tuple[str, float | None]]:
    return [
        (p, v) for p, v in zip(periods, values, strict=True) if not p.startswith(("TTM", "Interim"))
    ]


def _row(statement: Any, names: tuple[str, ...]) -> list[float | None] | None:
    for name in names:
        for row in statement.rows:
            if row.name == name:
                return row.values
    return None


def growth_figures(tables: dict[str, Any]) -> tuple[str | None, dict[str, float | None]]:
    income = build_statement(tables, statement="income", periods=12).statement
    revenue = _row(income, _REVENUE)
    profit = _row(income, ("Net Profit",))
    figures: dict[str, float | None] = {
        "revenue_latest_year_crore": None,
        "revenue_growth_percent": None,
        "net_profit_growth_percent": None,
        "revenue_cagr_3y_percent": None,
    }
    latest_year = None
    if revenue:
        years = _annual(income.periods, revenue)
        if years:
            latest_year = years[-1][0]
            figures["revenue_latest_year_crore"] = years[-1][1]
        if len(years) >= 2:
            figures["revenue_growth_percent"] = growth_percent(years[-1][1], years[-2][1])
        if len(years) >= 4:
            figures["revenue_cagr_3y_percent"] = cagr_percent(years[-4][1], years[-1][1], 3)
    if profit:
        years = _annual(income.periods, profit)
        if len(years) >= 2:
            figures["net_profit_growth_percent"] = growth_percent(years[-1][1], years[-2][1])
    return latest_year, figures


def register(server: MCPServer, *, client: TijoriClient, cache: Cache, read_only: Any) -> None:
    tool: Callable = server.tool(annotations=read_only)

    @tool
    async def compare_companies(
        companies: Annotated[list[CompanyQuery], Field(min_length=2, max_length=6)],
    ) -> Envelope[Comparison]:
        """Compare 2 to 6 companies side by side on valuation, returns and growth.

        Growth is calculated here from annual figures, never from TTM or
        interim columns: revenue and net profit growth in the latest year,
        and three-year revenue CAGR. Growth is blank where it isn't defined,
        such as from a loss. Also gives the minimum, median and maximum of
        each figure. For a company's own peer list, see company_snapshot.
        """
        rows = []
        sources = []
        warnings = []
        seen = set()
        for query in companies:
            match = await find_one(client, cache, query)
            if match.company.slug in seen:
                raise TearsheetError(ErrorCode.INVALID_INPUT, f"{query!r} is listed twice.")
            seen.add(match.company.slug)
            data, _ = await load_company(client, cache, match.company.slug)
            tables, _ = await load_tables(client, cache, match.company.slug)
            latest_year, growth = growth_figures(tables)
            page = data.page
            ratios = {r.name: r.value for r in page.ratios}
            values = {
                "price_rupees": page.price,
                "market_cap_crore": page.market_cap_crore,
                "pe": page.pe,
                "peg": page.peg,
                **{key: ratios.get(name) for name, key in _RATIO_PICKS.items()},
                **growth,
            }
            rows.append(
                CompanyRow(name=page.name, nse=page.nse, latest_year=latest_year, values=values)
            )
            sources.append(
                Source(provider="tijori", url=f"{BASE_URL}/company/{match.company.slug}/")
            )
        years = {row.latest_year for row in rows}
        if len(years) > 1:
            listed = ", ".join(sorted(filter(None, years)))
            warnings.append(f"Latest years differ ({listed}), so growth covers different periods.")
        stats = {metric: summary([row.values.get(metric) for row in rows]) for metric in METRICS}
        return to_result(
            Envelope[Comparison](
                data=Comparison(units=METRICS, companies=rows, summary=stats),
                sources=sources,
                warnings=warnings,
            )
        )
