"""The get_financials tool."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from tearsheet.core.cache import Cache
from tearsheet.core.envelope import Envelope, Source, Units, to_result
from tearsheet.core.errors import ErrorCode, ToolFailure
from tearsheet.sources.tijori.client import BASE_URL, TijoriClient
from tearsheet.sources.tijori.companies import find_one
from tearsheet.sources.tijori.financials import (
    Basis,
    Detail,
    FinancialStatement,
    Statement,
    build_statement,
    parse_fund_flow,
    parse_tables,
)
from tearsheet.tools.companies import CompanyQuery, entity_for

FINANCIALS_TTL_S = 6 * 3600


async def load_tables(
    client: TijoriClient, cache: Cache, slug: str
) -> tuple[dict[str, Any], datetime]:
    """Return a company's tables and when they were actually fetched."""
    entry = cache.get("financials", slug)
    if entry is not None:
        return entry.value, datetime.fromtimestamp(entry.fetched_at, UTC)
    response = await client.get(f"/company/{slug}/financials/")
    if response.status != 200:
        raise ToolFailure(
            ErrorCode.UPSTREAM_CHANGED, f"Tijori returned {response.status} for this company."
        )
    tables = parse_tables(response.text)
    cache.put("financials", slug, tables, ttl_s=FINANCIALS_TTL_S)
    return tables, datetime.fromtimestamp(cache.get("financials", slug).fetched_at, UTC)


async def _fund_flow(
    client: TijoriClient, cache: Cache, slug: str, periods: int
) -> tuple[Any, datetime]:
    from tearsheet.tools.company import load_company

    entry = cache.get("fund_flow", slug)
    if entry is None:
        data, _ = await load_company(client, cache, slug)
        if data.page.company_id is None:
            raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's page has no company id.")
        response = await client.get(f"/api/v1/ind/fund_flow_analysis_data/{data.page.company_id}/")
        cache.put("fund_flow", slug, response.json(), ttl_s=FINANCIALS_TTL_S)
        entry = cache.get("fund_flow", slug)
    return parse_fund_flow(entry.value, periods), datetime.fromtimestamp(entry.fetched_at, UTC)


def register(server: MCPServer, *, client: TijoriClient, cache: Cache, read_only: Any) -> None:
    tool: Callable = server.tool(annotations=read_only)

    @tool
    async def get_financials(
        company: CompanyQuery,
        statement: Statement = "income",
        basis: Basis = "consolidated",
        detail: Detail = "concise",
        periods: Annotated[int, Field(ge=1, le=12)] = 5,
    ) -> Envelope[FinancialStatement]:
        """Get a company's financial statement.

        Covers income statements, balance sheets, cash flow, quarterly results,
        ratios, and fund flow, which shows where money came from and went over
        trailing windows of 1 to 10 years. Accepts an NSE symbol, BSE code or
        name. Every row states its own unit, because statements mix crore,
        percent, days and multiples. A unit of as_reported means the unit isn't
        known, so don't assume one. A period starting TTM is trailing twelve
        months, and one starting Interim covers an unstated period, so don't
        compare either directly with annual columns. A blank value means no
        reliable figure exists. If the requested basis doesn't exist, the other
        is returned with a warning. Set detail to full for line items. Quarterly
        figures are checked against any matching filing in the filings folder,
        and the verification field says how that went. Other statements are
        Tijori's figures, unchecked.
        """
        match = await find_one(client, cache, company)
        if statement == "fund_flow":
            parsed, fetched_at = await _fund_flow(client, cache, match.company.slug, periods)
        else:
            tables, fetched_at = await load_tables(client, cache, match.company.slug)
            parsed = build_statement(
                tables, statement=statement, basis=basis, detail=detail, periods=periods
            )
        verification = None
        if statement == "quarterly":
            from tearsheet.tools.filings import verify_quarterly

            verification = verify_quarterly(parsed.statement, match.company.nse, match.company.bse)
        url = f"{BASE_URL}/company/{match.company.slug}/financials/"
        return to_result(
            Envelope[FinancialStatement](
                data=parsed.statement,
                entity=entity_for(match.company),
                as_of=parsed.as_of,
                retrieved_at=fetched_at,
                units=Units(),
                sources=[Source(provider="tijori", url=url)],
                warnings=parsed.warnings,
                **({"verification": verification} if verification else {}),
            )
        )
