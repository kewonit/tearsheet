"""Run Tijori screens safely.

Tijori silently ignores parameters it doesn't recognise, so a misnamed filter
returns a plausible, unfiltered list with no error. Two guards prevent that:
callers can only set the named arguments below, and every result is checked
against the query Tijori says it applied.
"""

import re
from typing import Any, Protocol
from urllib.parse import urlencode

from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.sources.tijori.client import Response

SCREEN_PATH = "/api/filter_queries/advanced_search/"


class Client(Protocol):
    async def get(self, path: str) -> Response: ...


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _clean_key(key: str) -> str:
    """Result keys can contain HTML, like <span>latest</span>Mcap."""
    return " ".join(re.sub(r"<[^>]+>", " ", key).split())


def _require_applied(name: str, sent: str, echoed: Any) -> None:
    if sent and _squash(sent) not in _squash(str(echoed or "")):
        raise TearsheetError(
            ErrorCode.UPSTREAM_CHANGED,
            f"Tijori didn't apply the {name} filter, so these results can't be trusted.",
        )


def _flag(value: bool) -> str:
    return "True" if value else "False"


async def run_screen(
    client: Client,
    *,
    financial: str = "",
    alternate: str = "",
    latest_results_only: bool = False,
    superstar_investors: bool = False,
    sme: bool = False,
) -> list[dict[str, Any]]:
    """Run a screen and return its rows, with HTML removed from the keys."""
    params = {
        "financial": financial,
        "alternate": alternate,
        "is_checked": _flag(latest_results_only),
        "whales": _flag(superstar_investors),
        "is_sme": _flag(sme),
        "columns": "",
        "query_id": "null",
        "source": "Basic",
    }
    response = await client.get(f"{SCREEN_PATH}?{urlencode(params)}")
    body = response.json()
    if not isinstance(body, dict):
        raise TearsheetError(ErrorCode.UPSTREAM_CHANGED, "Tijori's screener response changed.")
    if response.status == 500 or body.get("error"):
        raise TearsheetError(
            ErrorCode.INVALID_INPUT,
            "Tijori couldn't run that screen.",
            hint="Field names must match Tijori's catalogue exactly.",
        )
    _require_applied("financial", financial, body.get("financial_q"))
    _require_applied("alternate", alternate, body.get("alternate_q"))
    rows = body.get("data")
    if response.status != 200 or not isinstance(rows, list):
        raise TearsheetError(ErrorCode.UPSTREAM_CHANGED, "Tijori's screener response changed.")
    return [{_clean_key(key): value for key, value in row.items()} for row in rows]
