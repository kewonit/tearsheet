"""The find_company tool."""

from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from tearsheet.core.cache import Cache
from tearsheet.core.envelope import Entity, Envelope, Source, to_result
from tearsheet.sources.tijori.client import BASE_URL, TijoriClient
from tearsheet.sources.tijori.companies import Company, Match, MatchedOn, find

MAX_QUERY_LENGTH = 200
CompanyQuery = Annotated[str, Field(min_length=1, max_length=MAX_QUERY_LENGTH)]


class CompanyMatch(BaseModel):
    name: str
    slug: str
    nse: str | None = None
    bse: str | None = None
    market: str | None = None
    matched_on: MatchedOn


class CompanySearch(BaseModel):
    query: str
    matches: list[CompanyMatch]


def entity_for(company: Company) -> Entity:
    return Entity(name=company.name, nse=company.nse, bse=company.bse)


def _looks_like_a_symbol(query: str) -> bool:
    text = query.strip()
    return text.isupper() and " " not in text


def build_search(query: str, matches: list[Match]) -> Envelope[CompanySearch]:
    warnings = []
    if not matches:
        warnings.append(f"Nothing matched {query!r}. Try the company's name or BSE code.")
    elif _looks_like_a_symbol(query) and matches[0].matched_on in ("name", "search"):
        actual = ", ".join(sorted({m.company.nse for m in matches if m.company.nse}))
        note = f" The NSE symbol is {actual}." if actual and len(matches) == 1 else ""
        warnings.append(f"{query!r} isn't an NSE symbol, so this matched on the name.{note}")
    return Envelope[CompanySearch](
        data=CompanySearch(
            query=query,
            matches=[
                CompanyMatch(**match.company.model_dump(), matched_on=match.matched_on)
                for match in matches
            ],
        ),
        entity=entity_for(matches[0].company) if len(matches) == 1 else None,
        sources=[Source(provider="tijori", url=BASE_URL)],
        warnings=warnings,
    )


def register(server: MCPServer, *, client: TijoriClient, cache: Cache, read_only: Any) -> None:
    tool: Callable = server.tool(annotations=read_only)

    @tool
    async def find_company(query: CompanyQuery) -> Envelope[CompanySearch]:
        """Find a listed Indian company and its identifiers.

        Accepts an NSE symbol, a BSE code, a company name or part of one. Returns
        each match's name, NSE symbol, BSE code and slug, plus what it matched on.
        Use this when a name is ambiguous or you need the identifiers. Other tools
        accept the same input, so you don't need to call this first. An empty
        match list means nothing was found. ISINs aren't available. Check the
        warnings: if the input wasn't a real symbol, they give the actual one.
        """
        return to_result(build_search(query, await find(client, cache, query)))
