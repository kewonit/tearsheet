"""The get_sector_view tool."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from tearsheet.core.cache import Cache
from tearsheet.core.envelope import Envelope, Source, to_result
from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.sources.tijori.client import BASE_URL, TijoriClient
from tearsheet.sources.tijori.markets import (
    Constituent,
    Kind,
    MarketRow,
    MarketTable,
    load_constituents,
    parse_markets,
)

MARKETS_TTL_S = 3600
CONSTITUENTS_TTL_S = 6 * 3600


class SectorView(BaseModel):
    kind: Kind
    columns: list[str]
    rows: list[MarketRow]
    constituents: list[Constituent] | None


def register(server: MCPServer, *, client: TijoriClient, cache: Cache, read_only: Any) -> None:
    tool: Callable = server.tool(annotations=read_only)

    async def markets() -> tuple[dict[str, MarketTable], datetime]:
        entry = cache.get("markets", "monitor")
        if entry is None:
            response = await client.get("/in/markets")
            tables = parse_markets(response.text)
            cache.put(
                "markets",
                "monitor",
                {k: v.model_dump() for k, v in tables.items()},
                ttl_s=MARKETS_TTL_S,
            )
            entry = cache.get("markets", "monitor")
        tables = {k: MarketTable(**v) for k, v in entry.value.items()}
        return tables, datetime.fromtimestamp(entry.fetched_at, UTC)

    @tool
    async def get_sector_view(
        kind: Kind = "sectors",
        name: Annotated[str | None, Field(max_length=100)] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 30,
    ) -> Envelope[SectorView]:
        """Get market indices, Tijori's sector indices or conglomerate groups.

        Without a name, lists them with their price changes over periods such
        as 1D, 1M and 1YR*. With a name, such as "Private Bank" or "Adani",
        also returns that sector's or group's constituent companies and their
        weights. Tijori marks some periods with an asterisk and doesn't say
        what it means, so mention that when quoting them.
        """
        tables, fetched_at = await markets()
        table = tables[kind]
        rows = table.rows
        constituents = None
        warnings = []
        if any("*" in column for column in table.columns):
            warnings.append("Periods marked * aren't explained by Tijori.")
        if name:
            wanted = name.strip().lower()
            found = [r for r in rows if wanted in r.name.lower()]
            exact = [r for r in found if r.name.lower() == wanted]
            found = exact or found
            if not found:
                raise TearsheetError(
                    ErrorCode.NOT_FOUND,
                    f"No {kind} entry matched {name!r}.",
                    hint=f"Some options: {', '.join(r.name for r in rows[:15])}.",
                )
            if len(found) > 1:
                raise TearsheetError(
                    ErrorCode.INVALID_INPUT,
                    f"{name!r} matches several: {', '.join(r.name for r in found[:10])}.",
                )
            rows = found
            row = found[0]
            if kind == "indices" or row.market_id is None:
                warnings.append("Tijori doesn't list constituents for this entry.")
            else:
                key = f"{kind}:{row.market_id}"
                entry = cache.get("constituents", key)
                if entry is None:
                    found_constituents = await load_constituents(client, kind, row.market_id)
                    cache.put(
                        "constituents",
                        key,
                        [c.model_dump() for c in found_constituents],
                        ttl_s=CONSTITUENTS_TTL_S,
                    )
                    entry = cache.get("constituents", key)
                constituents = [Constituent(**item) for item in entry.value][:limit]
        return to_result(
            Envelope[SectorView](
                data=SectorView(
                    kind=kind, columns=table.columns, rows=rows[:limit], constituents=constituents
                ),
                retrieved_at=fetched_at,
                sources=[Source(provider="tijori", url=f"{BASE_URL}/in/markets")],
                warnings=warnings,
                next_cursor=None,
            )
        )
