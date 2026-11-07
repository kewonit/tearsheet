"""Read Tijori's market monitor: indices, sector indices and conglomerates."""

import re
from typing import Literal, Protocol

from pydantic import BaseModel

from tearsheet.core.errors import ErrorCode, ToolFailure
from tearsheet.sources.tijori.client import Response
from tearsheet.sources.tijori.pages import clean_text, number, table_rows

Kind = Literal["indices", "sectors", "conglomerates"]
TABLES: dict[str, str] = {
    "indices": "market__table__headline",
    "sectors": "market__table__niche",
    "conglomerates": "market__table__groups",
}
# Sectors and conglomerates each have their own constituents endpoint. The
# wrong one returns an empty list rather than an error.
CONSTITUENTS: dict[str, str] = {
    "sectors": "/api/v1/niche/price/{id}/",
    "conglomerates": "/api/v1/groups/price/{id}/",
}
_SKIP_COLUMNS = {"", "weight"}


class Client(Protocol):
    async def get(self, path: str) -> Response: ...


class MarketRow(BaseModel):
    name: str
    market_id: str | None
    values: dict[str, float | None]


class MarketTable(BaseModel):
    kind: Kind
    columns: list[str]
    rows: list[MarketRow]


class Constituent(BaseModel):
    name: str
    slug: str | None
    weight_percent: float | None


def _name(cell: str) -> str:
    """Rows look like 'TJI Banks + 9 17', where the trailing parts are page controls."""
    return clean_text(re.sub(r"\s*\+.*$", "", cell), 80)


def parse_markets(html: str) -> dict[str, MarketTable]:
    tables = {}
    for kind, table_id in TABLES.items():
        rows = table_rows(html, table_id)
        if not rows:
            raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, f"Tijori's {kind} table is empty.")
        header = rows[0].cells
        keep = [i for i, label in enumerate(header) if label.strip().lower() not in _SKIP_COLUMNS]
        parsed = []
        for row in rows[1:]:
            if len(row.cells) != len(header):
                continue
            values = {header[i]: number(row.cells[i]) for i in keep}
            parsed.append(
                MarketRow(
                    name=_name(row.cells[0]),
                    market_id=row.attrs.get("tjiid") or None,
                    values=values,
                )
            )
        tables[kind] = MarketTable(kind=kind, columns=[header[i] for i in keep], rows=parsed)  # type: ignore[arg-type]
    return tables


async def load_constituents(client: Client, kind: str, market_id: str) -> list[Constituent]:
    if not market_id.isdigit():
        raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's market id isn't a number.")
    body = (await client.get(CONSTITUENTS[kind].format(id=market_id))).json()
    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list):
        raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's constituents changed shape.")
    constituents = [
        Constituent(
            name=clean_text(item.get("name"), 80),
            slug=item.get("slug"),
            weight_percent=number(item.get("weight")),
        )
        for item in items
        if isinstance(item, dict) and item.get("name")
    ]
    if constituents and not any(c.weight_percent for c in constituents):
        constituents = [c.model_copy(update={"weight_percent": None}) for c in constituents]
    return constituents
