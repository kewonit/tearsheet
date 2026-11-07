"""Find companies by NSE symbol, BSE code or name.

Tijori's search matches names, not symbols, and its company pages don't show
symbols at all. Its screener rows do, so one market-wide screen builds a local
index that makes symbol lookups exact. Tijori exposes no ISINs.
"""

import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from tearsheet.core.cache import Cache
from tearsheet.core.errors import ErrorCode, ToolFailure
from tearsheet.sources.tijori.client import Response
from tearsheet.sources.tijori.screener import run_screen

INDEX_TTL_S = 7 * 24 * 3600
WHOLE_MARKET = "Market Capitalization > 0"
MIN_NAME_LENGTH = 3
MAX_NAME_MATCHES = 5

MatchedOn = Literal["nse_symbol", "bse_code", "slug", "name", "search"]


class Client(Protocol):
    async def get(self, path: str) -> Response: ...


class Company(BaseModel):
    name: str
    slug: str
    nse: str | None = None
    bse: str | None = None
    market: Literal["main", "sme"] | None = None


@dataclass(frozen=True)
class Match:
    company: Company
    matched_on: MatchedOn


def _from_row(row: dict[str, Any], market: Literal["main", "sme"]) -> Company:
    code = row.get("scripcode")
    return Company(
        name=row["name"],
        slug=row["slug"],
        nse=row.get("nse symbol") or None,
        bse=str(code) if code else None,
        market=market,
    )


async def load_index(client: Client, cache: Cache) -> list[Company]:
    """Return every listed company, refreshing the local index weekly."""
    entry = cache.get("companies", "index")
    if entry is not None:
        return [Company(**item) for item in entry.value]
    companies = []
    try:
        for market, sme in (("main", False), ("sme", True)):
            rows = await run_screen(client, financial=WHOLE_MARKET, sme=sme)
            companies += [_from_row(row, market) for row in rows]
    except (KeyError, ValidationError) as exc:
        raise ToolFailure(
            ErrorCode.UPSTREAM_CHANGED, "Tijori's screener rows changed shape."
        ) from exc
    if not companies:
        raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's screener returned no companies.")
    # Companies that moved from SME to the main board appear in both screens.
    unique: dict[str, Company] = {}
    for company in companies:
        unique.setdefault(company.slug, company)
    companies = list(unique.values())
    cache.put(
        "companies", "index", [company.model_dump() for company in companies], ttl_s=INDEX_TTL_S
    )
    return companies


def _normalise(text: str) -> str:
    squashed = re.sub(r"[^a-z0-9]", "", text.lower())
    return re.sub(r"(limited|ltd)$", "", squashed)


def resolve(query: str, companies: list[Company]) -> list[Match]:
    """Match a query against the index, most exact first, stopping at the first hit."""
    text = query.strip()
    upper = text.upper()
    symbols = [c for c in companies if c.nse and c.nse.upper() == upper]
    if symbols:
        return [Match(c, "nse_symbol") for c in symbols]
    if text.isdigit():
        codes = [c for c in companies if c.bse == text]
        if codes:
            return [Match(c, "bse_code") for c in codes]
    slugs = [c for c in companies if c.slug == text.lower()]
    if slugs:
        return [Match(c, "slug") for c in slugs]

    wanted = _normalise(text)
    if len(wanted) < MIN_NAME_LENGTH:
        return []
    exact = [c for c in companies if wanted in (_normalise(c.name), _normalise(c.slug))]
    if exact:
        return [Match(c, "name") for c in exact]
    starts = [
        c
        for c in companies
        if _normalise(c.name).startswith(wanted) or _normalise(c.slug).startswith(wanted)
    ]
    starts.sort(key=lambda c: len(c.name))
    return [Match(c, "name") for c in starts[:MAX_NAME_MATCHES]]


async def search_by_name(client: Client, query: str, companies: list[Company]) -> list[Match]:
    """Fall back to Tijori's own search, which also matches parts of names."""
    response = await client.get(f"/api/v1/ind/company_search/?q={quote(query)}")
    results = response.json()
    if not isinstance(results, list):
        raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's search response changed.")
    known = {company.slug: company for company in companies}
    matches = []
    for item in results:
        if item.get("type") == "companies" and item.get("slug") and item.get("name"):
            company = known.get(item["slug"]) or Company(name=item["name"], slug=item["slug"])
            matches.append(Match(company, "search"))
    return matches[:MAX_NAME_MATCHES]


async def find(client: Client, cache: Cache, query: str) -> list[Match]:
    if not query.strip():
        return []
    companies = await load_index(client, cache)
    return resolve(query, companies) or await search_by_name(client, query, companies)


async def find_one(client: Client, cache: Cache, query: str) -> Match:
    """Return exactly one company, or an error saying how to narrow it down."""
    matches = await find(client, cache, query)
    if not matches:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"No company matched {query!r}.",
            hint="Try the company's name, or its BSE code.",
        )
    if len(matches) > 1:
        options = ", ".join(
            f"{m.company.name} ({m.company.nse or m.company.slug})" for m in matches
        )
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"{query!r} matches more than one company: {options}.",
            hint="Use the exact NSE symbol or slug.",
        )
    return matches[0]
