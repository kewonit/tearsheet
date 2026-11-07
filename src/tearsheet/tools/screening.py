"""The screen_stocks and search_screen_fields tools."""

import hashlib
import json
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from tearsheet.core.cache import Cache
from tearsheet.core.envelope import Envelope, Source, to_result
from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.sources.tijori.catalogue import check_query, load_catalogue, search_fields
from tearsheet.sources.tijori.client import BASE_URL, TijoriClient
from tearsheet.sources.tijori.screener import Preset, load_presets, run_screen
from tearsheet.tools.plan import session_plan

SCREEN_TTL_S = 30 * 60
PRESETS_TTL_S = 24 * 3600
_IDENTITY = {"name", "slug", "scripcode", "nse symbol", "segment"}


class Column(BaseModel):
    name: str
    unit: str


class ScreenRow(BaseModel):
    name: str
    nse: str | None
    bse: str | None
    segment: str | None
    values: dict[str, float | str | None]


class ScreenResult(BaseModel):
    query: str
    total: int
    columns: list[Column]
    rows: list[ScreenRow]


class FieldMatch(BaseModel):
    name: str
    unit: str
    period: str


class FieldSearch(BaseModel):
    query: str
    fields: list[FieldMatch]


class PresetInfo(BaseModel):
    name: str
    category: str
    description: str
    paid_only: bool


def _column_unit(name: str, units: dict[str, str]) -> str:
    lowered = name.lower()
    for suffix, unit in ((" cr", "crore"), (" %", "percent"), ("(%)", "percent")):
        if lowered.endswith(suffix):
            return unit
    return units.get(lowered, "as_reported")


def _value(value: Any) -> float | str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return round(float(value), 4)
    return str(value)[:80]


def shape_rows(
    raw: list[dict[str, Any]], units: dict[str, str]
) -> tuple[list[Column], list[ScreenRow]]:
    names = [key for key in (raw[0] if raw else {}) if key.lower() not in _IDENTITY]
    columns = [Column(name=name, unit=_column_unit(name, units)) for name in names]
    rows = [
        ScreenRow(
            name=str(item.get("name") or ""),
            nse=item.get("nse symbol") or None,
            bse=str(item["scripcode"]) if item.get("scripcode") else None,
            segment=item.get("segment") or None,
            values={name: _value(item.get(name)) for name in names},
        )
        for item in raw
    ]
    return columns, rows


def _sort(rows: list[ScreenRow], column: str, descending: bool) -> list[ScreenRow]:
    def key(row: ScreenRow) -> tuple[bool, float]:
        value = row.values.get(column)
        number = value if isinstance(value, float) else None
        return (number is None, -(number or 0.0) if descending else (number or 0.0))

    return sorted(rows, key=key)


def _match_preset(presets: list[Preset], name: str) -> Preset:
    wanted = name.strip().lower()
    exact = [p for p in presets if p.name.lower() == wanted]
    partial = [p for p in presets if wanted in p.name.lower()]
    found = exact or partial
    if len(found) != 1:
        options = ", ".join(sorted(p.name for p in presets))
        problem = "matches several presets" if found else "isn't a preset"
        raise TearsheetError(
            ErrorCode.INVALID_INPUT, f"{name!r} {problem}.", hint=f"Presets: {options}."
        )
    return found[0]


def register(server: MCPServer, *, client: TijoriClient, cache: Cache, read_only: Any) -> None:
    tool: Callable = server.tool(annotations=read_only)

    async def presets() -> list[Preset]:
        entry = cache.get("presets", "all")
        if entry is None:
            found = await load_presets(client)
            cache.put("presets", "all", [p.model_dump() for p in found], ttl_s=PRESETS_TTL_S)
            return found
        return [Preset(**item) for item in entry.value]

    @tool
    async def search_screen_fields(
        query: Annotated[str, Field(min_length=1, max_length=100)],
        limit: Annotated[int, Field(ge=1, le=50)] = 15,
    ) -> Envelope[FieldSearch]:
        """Find exact screener field names, with their units and periods.

        screen_stocks needs exact field names, such as "ROCE" or "3yr Avg ROCE".
        Search by words, like "roce" or "debt equity". Also lists the preset
        screens when query is "presets". Searching is local and cheap.
        """
        if query.strip().lower() == "presets":
            found = await presets()
            listed = [
                FieldMatch(
                    name=p.name,
                    unit="preset",
                    period=f"{p.category}{', paid plan' if p.paid_only else ''}",
                )
                for p in found
            ]
            return to_result(Envelope[FieldSearch](data=FieldSearch(query=query, fields=listed)))
        fields = await load_catalogue(client, cache)
        matches = [FieldMatch(**f.model_dump()) for f in search_fields(fields, query, limit)]
        warnings = [] if matches else [f"No field matched {query!r}. Try fewer or different words."]
        return to_result(
            Envelope[FieldSearch](
                data=FieldSearch(query=query, fields=matches),
                sources=[Source(provider="tijori", url=f"{BASE_URL}/filter/")],
                warnings=warnings,
            )
        )

    @tool
    async def screen_stocks(
        financial: Annotated[str | None, Field(max_length=500)] = None,
        business: Annotated[str | None, Field(max_length=300)] = None,
        preset: Annotated[str | None, Field(max_length=100)] = None,
        latest_results_only: bool = False,
        superstar_investors: bool = False,
        sme: bool = False,
        sort_by: Annotated[str | None, Field(max_length=100)] = None,
        descending: bool = True,
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
        cursor: Annotated[str | None, Field(max_length=20)] = None,
    ) -> Envelope[ScreenResult]:
        """Find listed companies matching conditions, across the whole market.

        financial is a condition on exact field names, such as
        "Market Capitalization > 1000 AND ROCE > 20%". Find names with
        search_screen_fields. business filters on what companies do, such as
        "makes Steel" or "has plant in Gujarat". Or pass a preset name instead.
        Results are checked to make sure Tijori applied every filter. Use
        sort_by with a column name, and pass next_cursor back to page through
        results. Main board by default; set sme for SME listings.
        """
        if preset and (financial or business):
            raise TearsheetError(
                ErrorCode.INVALID_INPUT, "Use a preset or your own filters, not both."
            )
        if not (preset or financial or business):
            raise TearsheetError(
                ErrorCode.INVALID_INPUT,
                "Give a financial condition, a business filter or a preset.",
                hint="For example: financial='Market Capitalization > 1000 AND ROCE > 20%'.",
            )
        fields = await load_catalogue(client, cache)
        units = {f.name.lower(): f.unit for f in fields}
        chosen = None
        if preset:
            chosen = _match_preset(await presets(), preset)
            if chosen.paid_only and await session_plan(client, cache) == "free":
                raise TearsheetError(
                    ErrorCode.PLAN_REQUIRED,
                    f"The {chosen.name!r} preset needs a paid Tijori plan.",
                    hint="Use a free preset or your own filters.",
                )
        elif financial:
            check_query(financial, fields)
        arguments = {
            "financial": chosen.financial if chosen else financial or "",
            "alternate": chosen.business if chosen else business or "",
            "latest_results_only": latest_results_only,
            "superstar_investors": chosen.superstar_investors if chosen else superstar_investors,
            "sme": sme,
            "preset_id": chosen.preset_id if chosen else None,
        }
        key = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()[:24]
        entry = cache.get("screens", key)
        if entry is None:
            raw = await run_screen(client, **arguments)
            cache.put("screens", key, raw, ttl_s=SCREEN_TTL_S)
            entry = cache.get("screens", key)
        columns, rows = shape_rows(entry.value, units)
        if sort_by:
            if sort_by not in {c.name for c in columns}:
                raise TearsheetError(
                    ErrorCode.INVALID_INPUT,
                    f"Can't sort by {sort_by!r}.",
                    hint=f"Columns: {', '.join(c.name for c in columns)}.",
                )
            rows = _sort(rows, sort_by, descending)
        start = int(cursor) if cursor and cursor.isdigit() else 0
        page = rows[start : start + limit]
        more = start + limit < len(rows)
        description = chosen.name if chosen else " | ".join(filter(None, [financial, business]))
        return to_result(
            Envelope[ScreenResult](
                data=ScreenResult(query=description, total=len(rows), columns=columns, rows=page),
                sources=[Source(provider="tijori", url=f"{BASE_URL}/filter/")],
                warnings=[] if rows else ["No companies matched."],
                next_cursor=str(start + limit) if more else None,
            )
        )
