"""The MCP server. Tools are registered in a fixed order, which helps clients cache them."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from mcp.server.caching import CacheHint
from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel

from tearsheet import __version__
from tearsheet.core import paths
from tearsheet.core.cache import Cache
from tearsheet.core.envelope import Envelope, to_result
from tearsheet.core.session import SessionState, read_session_info
from tearsheet.sources.tijori.client import TijoriClient
from tearsheet.tools import companies, company, compare, filings, financials, markets, screening

INSTRUCTIONS = (
    "Tearsheet gives facts and calculations for researching Indian listed companies, "
    "using the user's own Tijori Finance account and filings they added themselves. "
    "It does not give investment advice. Every result says how old its data is and "
    "whether it was checked against a filing, so report those alongside any figure."
)

READ_ONLY = ToolAnnotations(read_only_hint=True)
ONE_HOUR_MS = 3_600_000
FILING_SUFFIXES = {".xml", ".xbrl", ".pdf"}

SIGN_IN = "Ask the user to run: tearsheet login"
_SESSION_WARNINGS = {
    SessionState.NONE: f"Not signed in. {SIGN_IN}",
    SessionState.EXPIRED: f"The saved session has expired. {SIGN_IN}",
    SessionState.UNREADABLE: f"The saved session can't be read. {SIGN_IN}",
}


class ServerStatus(BaseModel):
    version: str
    session: SessionState
    session_saved_at: datetime | None = None
    session_expires_at: datetime | None = None
    cache_entries: dict[str, int]
    filings_dir: str
    filings_found: int


def _count_filings(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(
        1 for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in FILING_SUFFIXES
    )


def collect_status(session_file: Path, cache: Cache, filings: Path) -> Envelope[ServerStatus]:
    session = read_session_info(session_file)
    filings_found = _count_filings(filings)

    warnings = []
    if session.state in _SESSION_WARNINGS:
        warnings.append(_SESSION_WARNINGS[session.state])
    if session.loose_permissions:
        warnings.append(f"Other users can read the session file. Run: chmod 600 {session_file}")
    if filings_found == 0:
        warnings.append(f"No filings found in {filings}, so no figure can be verified yet.")

    return Envelope[ServerStatus](
        data=ServerStatus(
            version=__version__,
            session=session.state,
            session_saved_at=session.saved_at,
            session_expires_at=session.expires_at,
            cache_entries=cache.counts(),
            filings_dir=str(filings),
            filings_found=filings_found,
        ),
        warnings=warnings,
    )


def build_server() -> MCPServer:
    client = TijoriClient(paths.session_path())

    @asynccontextmanager
    async def close_browser_on_exit(_: MCPServer) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await client.close()

    server = MCPServer(
        "tearsheet",
        version=__version__,
        instructions=INSTRUCTIONS,
        cache_hints={
            "server/discover": CacheHint(ttl_ms=ONE_HOUR_MS, scope="public"),
            "tools/list": CacheHint(ttl_ms=ONE_HOUR_MS, scope="public"),
        },
        lifespan=close_browser_on_exit,
    )
    cache = Cache(paths.cache_path())
    companies.register(server, client=client, cache=cache, read_only=READ_ONLY)
    financials.register(server, client=client, cache=cache, read_only=READ_ONLY)
    company.register(server, client=client, cache=cache, read_only=READ_ONLY)
    screening.register(server, client=client, cache=cache, read_only=READ_ONLY)
    compare.register(server, client=client, cache=cache, read_only=READ_ONLY)
    markets.register(server, client=client, cache=cache, read_only=READ_ONLY)
    filings.register(server, client=client, cache=cache, read_only=READ_ONLY)

    @server.tool(annotations=READ_ONLY)
    def server_status() -> Envelope[ServerStatus]:
        """Report whether Tearsheet is ready to use.

        Shows whether a Tijori session is saved, what is in the local cache and
        how many filings the user has added. Call this first if another tool
        fails, or when the user asks why data is missing. It works offline and
        never contacts Tijori, so a saved session may still have been ended on
        Tijori's side. It returns no company data.
        """
        return to_result(collect_status(paths.session_path(), cache, paths.filings_dir()))

    return server
