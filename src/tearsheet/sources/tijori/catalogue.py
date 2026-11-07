"""Tijori's screener field catalogue: searched locally, and used to check queries.

Searching the catalogue through Tijori only covers financial fields, so the
full catalogue is fetched once a week and searched here.
"""

import difflib
import re
from functools import lru_cache
from typing import Protocol

from pydantic import BaseModel

from tearsheet.core.cache import Cache
from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.sources.tijori.client import Response

CATALOGUE_PATH = "/api/filter_queries/filter_field_search/?q=&query_type=financials"
CATALOGUE_TTL_S = 7 * 24 * 3600
_UNITS = {"cr": "crore", "%": "percent", "days": "days", "rs": "rupees"}
_PERIODS = {"val": "latest", "q": "latest quarter", "lastyear": "last year", "ago": "years ago"}
_CLAUSE_SPLIT = re.compile(r"\s+(?:AND|OR)\s+", re.IGNORECASE)
_OPERATORS = re.compile(r"<=|>=|!=|==|[<>=+\-*/()]")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?%?$")
_FIELD = " FIELDMATCH "


class Client(Protocol):
    async def get(self, path: str) -> Response: ...


class Field(BaseModel):
    name: str
    unit: str
    period: str


async def load_catalogue(client: Client, cache: Cache) -> list[Field]:
    entry = cache.get("catalogue", "fields")
    if entry is not None:
        return [Field(**item) for item in entry.value]
    body = (await client.get(CATALOGUE_PATH)).json()
    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list) or not items:
        raise TearsheetError(ErrorCode.UPSTREAM_CHANGED, "Tijori's field catalogue changed shape.")
    fields = [
        Field(
            name=str(item["value"]),
            unit=_UNITS.get(str(item.get("unit") or "").strip().lower(), "as_reported"),
            period=_PERIODS.get(str(item.get("timeperiod")), str(item.get("timeperiod") or "")),
        )
        for item in items
        if isinstance(item, dict) and item.get("value")
    ]
    cache.put("catalogue", "fields", [f.model_dump() for f in fields], ttl_s=CATALOGUE_TTL_S)
    return fields


def search_fields(fields: list[Field], query: str, limit: int) -> list[Field]:
    """Fields containing every word of the query, shortest names first."""
    words = query.lower().split()
    found = [f for f in fields if all(word in f.name.lower() for word in words)]
    found.sort(key=lambda f: (len(f.name), f.name))
    if found:
        return found[:limit]
    names = {f.name.lower(): f for f in fields}
    close = difflib.get_close_matches(query.lower(), list(names), n=limit, cutoff=0.6)
    return [names[name] for name in close]


@lru_cache(maxsize=4)
def _field_pattern(names: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted(names, key=len, reverse=True)
    return re.compile(
        "|".join(rf"(?<![\w&]){re.escape(name)}(?![\w&])" for name in ordered), re.IGNORECASE
    )


def check_query(query: str, fields: list[Field]) -> None:
    """Reject a query naming a field Tijori doesn't have, before it reaches Tijori.

    Tijori answers an unknown field with a bare server error. Known field names
    are matched first, longest first, because some contain the word "and", such
    as "Depreciation and Amortization". What remains between operators must be
    a number.
    """
    known = {f.name.lower() for f in fields}
    masked = _field_pattern(tuple(f.name for f in fields)).sub(_FIELD, query.strip())
    unknown = []
    for clause in _CLAUSE_SPLIT.split(masked):
        for operand in _OPERATORS.split(clause):
            text = " ".join(operand.split())
            if text and text != _FIELD.strip() and not _NUMBER.match(text):
                unknown.append(text)
    if unknown:
        suggestions = []
        names = {f.name.lower(): f.name for f in fields}
        for name in unknown[:3]:
            starts = sorted((n for n in known if n.startswith(name.lower())), key=len)[:3]
            close = starts or difflib.get_close_matches(name.lower(), list(known), n=2, cutoff=0.6)
            if close:
                options = " or ".join(repr(names[c]) for c in close)
                suggestions.append(f"{name!r}: did you mean {options}?")
        raise TearsheetError(
            ErrorCode.INVALID_INPUT,
            f"Unknown screener field: {', '.join(repr(u) for u in unknown[:3])}.",
            hint=" ".join(suggestions) or "Use search_screen_fields to find exact field names.",
        )
