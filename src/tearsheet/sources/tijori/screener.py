"""Run Tijori screens safely.

Tijori silently ignores parameters it doesn't recognise, so a misnamed filter
returns a plausible, unfiltered list with no error. Two guards prevent that:
callers can only set the named arguments below, and every result is checked
against the query Tijori says it applied.
"""

import re
from typing import Any, Protocol
from urllib.parse import urlencode

from pydantic import BaseModel

from tearsheet.core.errors import ErrorCode, ToolFailure
from tearsheet.sources.tijori.client import Response

SCREEN_PATH = "/api/filter_queries/advanced_search/"
PRESET_PATH = "/api/filter_queries/popular-query/results/"


class Client(Protocol):
    async def get(self, path: str) -> Response: ...


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _clean_key(key: str) -> str:
    """Result keys can contain HTML, like <span>latest</span>Mcap."""
    return " ".join(re.sub(r"<[^>]+>", " ", key).split())


def _require_applied(name: str, sent: str, echoed: Any) -> None:
    if sent and _squash(sent) not in _squash(str(echoed or "")):
        raise ToolFailure(
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
    preset_id: int | None = None,
) -> list[dict[str, Any]]:
    """Run a screen and return its rows, with HTML removed from the keys.

    A preset runs through Tijori's preset endpoint, which is the only one
    that applies a preset's business filter.
    """
    params = {
        "financial": financial,
        "alternate": alternate,
        "is_checked": _flag(latest_results_only),
        "whales": _flag(superstar_investors),
        "is_sme": _flag(sme),
        "columns": "",
        "query_id": "null" if preset_id is None else str(preset_id),
        "source": "Basic" if preset_id is None else "Popular",
    }
    path = SCREEN_PATH if preset_id is None else PRESET_PATH
    response = await client.get(f"{path}?{urlencode(params)}")
    body = response.json()
    if not isinstance(body, dict):
        raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's screener response changed.")
    if response.status == 500 or body.get("error"):
        detail = " ".join(str(body.get("error") or "").split())[:150]
        reason = f" Tijori said: {detail}." if detail else ""
        if preset_id is not None:
            raise ToolFailure(
                ErrorCode.UPSTREAM_CHANGED,
                f"Tijori's own preset failed to run.{reason}",
                hint="This is a fault in Tijori's preset. Try another preset or your own filters.",
            )
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Tijori couldn't run that screen.{reason}",
            hint="Field names must match Tijori's catalogue exactly.",
        )
    _require_applied("financial", financial, body.get("financial_q"))
    _require_applied("alternate", alternate, body.get("alternate_q"))
    rows = body.get("data")
    if response.status != 200 or not isinstance(rows, list):
        raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's screener response changed.")
    return [{_clean_key(key): value for key, value in row.items()} for row in rows]


PRESETS_PATH = "/api/filter_queries/popular-query/"


class Preset(BaseModel):
    preset_id: int
    name: str
    category: str
    description: str
    paid_only: bool
    financial: str
    business: str
    superstar_investors: bool


async def load_presets(client: Client) -> list[Preset]:
    body = (await client.get(PRESETS_PATH)).json()
    if not isinstance(body, dict):
        raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's preset list changed shape.")
    presets = []
    for category, items in body.items():
        for item in items if isinstance(items, list) else []:
            try:
                presets.append(
                    Preset(
                        preset_id=int(item["id"]),
                        name=str(item["name"]),
                        category=str(category),
                        description=" ".join(str(item.get("description") or "").split())[:200],
                        paid_only=str(item.get("plan_tier") or "").lower() != "free",
                        financial=str(item.get("financial_query") or ""),
                        business=str(item.get("alt_query") or ""),
                        superstar_investors=bool(item.get("whales")),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ToolFailure(
                    ErrorCode.UPSTREAM_CHANGED, "Tijori's preset list changed shape."
                ) from exc
    return presets
