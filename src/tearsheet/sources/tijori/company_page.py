"""Read a company's overview page into the facts Tearsheet returns.

Only facts are kept. Tijori's own commentary, such as its investment thesis and
red or green flags, is left out: Tearsheet doesn't pass on advice, and that
text is Tijori's analysis rather than data.
"""

import json
import re
from datetime import date
from html.parser import HTMLParser
from typing import Any

from pydantic import BaseModel

from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.sources.tijori.pages import (
    clean_text,
    date_from_epoch_ms,
    json_blocks,
    month_label,
    number,
    require_block,
)

# Tijori doesn't say whether longer returns are annualised, and they've looked
# wrong in testing, so only these are reported.
RETURN_PERIODS = ("1d", "1m", "6m", "ytd", "1y")
MAX_DIVIDENDS = 5
MAX_EVENTS = 5
_RATIO_UNITS = {"cr": "crore", "crs": "crore", "%": "percent", "rs": "rupees"}
_MULTIPLE_RATIOS = {
    "debt to equity ratio",
    "ev by ebitda",
    "interest coverage ratios",
    "pe",
    "peg ratio",
}
_RUPEE_RATIOS = {"latest price"}


class Figure(BaseModel):
    name: str
    value: float | None
    unit: str


class Average(BaseModel):
    name: str
    latest: float | None
    three_year: float | None
    five_year: float | None
    unit: str


class Dividend(BaseModel):
    ex_date: str
    details: str


class KeyEvent(BaseModel):
    date: str
    event: str


class Entitlements(BaseModel):
    """What the session's Tijori plan unlocks. Anything unknown counts as locked."""

    plan_tier: str = "free"
    metrics_history: bool = False
    revenue_mix_history: bool = False
    market_share_history: bool = False


class CompanyPage(BaseModel):
    name: str
    nse: str | None
    status: str | None
    classification: str | None
    is_banking: bool
    company_id: int | None
    price: float | None
    price_date: date | None
    market_cap_crore: float | None
    pe: float | None
    peg: float | None
    ratios: list[Figure]
    averages: list[Average]
    returns_percent: dict[str, float | None]
    dividends: list[Dividend]
    key_events: list[KeyEvent]
    peers: list[dict[str, Any]]
    peer_columns: list[Figure]
    entitlements: Entitlements


def normalise_unit(unit: str) -> str:
    """Map Tijori's unit labels to Tearsheet's. Unknown labels pass through unchanged."""
    cleaned = unit.strip()
    return _RATIO_UNITS.get(cleaned.lower(), cleaned or "as_reported")


def _ratio_unit(name: str, unit: str) -> str:
    mapped = _RATIO_UNITS.get(unit.strip().lower())
    if mapped:
        return mapped
    lowered = name.strip().lower()
    if "%" in lowered:
        return "percent"
    if lowered in _RUPEE_RATIOS:
        return "rupees"
    return "multiple" if lowered in _MULTIPLE_RATIOS else "as_reported"


def _locked(locks: dict[str, Any], feature: str) -> bool:
    value = (locks.get(feature) or {}).get("historic")
    return value is not True


def _entitlements(blocks: dict[str, Any]) -> Entitlements:
    plan = blocks.get("plan_details") if isinstance(blocks.get("plan_details"), dict) else {}
    locks = blocks.get("overview_locks") if isinstance(blocks.get("overview_locks"), dict) else {}
    overview = ((plan.get("ind_company") or {}).get("overview") or {}) if plan else {}
    revenue_mix = (overview.get("rev_mix") or {}).get("historic") is True
    return Entitlements(
        plan_tier=str(plan.get("plan_tier") or "free"),
        metrics_history=not _locked(locks, "op_metrics"),
        revenue_mix_history=revenue_mix and not _locked(locks, "rev_mix"),
        market_share_history=not _locked(locks, "market_share"),
    )


def _averages(details: dict[str, Any]) -> list[Average]:
    averages = []
    for item in (details.get("quick_look") or {}).get("table_data") or []:
        cells = {str(label).strip().lower(): text for label, text in item.get("data") or []}
        sample = next(iter(cells.values()), "")
        averages.append(
            Average(
                name=clean_text(item.get("name"), 60),
                latest=number(cells.get("latest")),
                three_year=number(cells.get("3yr average")),
                five_year=number(cells.get("5yr average")),
                unit="percent" if "%" in str(sample) else "as_reported",
            )
        )
    return averages


def _price(blocks: dict[str, Any]) -> tuple[float | None, date | None]:
    points = blocks.get("intraday_price")
    if (
        isinstance(points, list)
        and points
        and isinstance(points[-1], list)
        and len(points[-1]) == 2
    ):
        return number(points[-1][1]), date_from_epoch_ms(points[-1][0])
    return None, None


def _peers(blocks: dict[str, Any]) -> tuple[list[Figure], list[dict[str, Any]]]:
    table = blocks.get("peers_table_data")
    if not isinstance(table, list) or len(table) < 2:
        return [], []
    columns = [
        Figure(
            name=c.get("name", ""),
            value=None,
            unit=_ratio_unit(c.get("name", ""), c.get("unit", "")),
        )
        for c in (table[0] or {}).get("columns") or []
    ]
    rows = []
    for row in (table[1] or {}).get("data") or []:
        entry = {"name": clean_text(row.get("name"), 80), "slug": row.get("slug")}
        entry.update({column.name: number(row.get(column.name)) for column in columns})
        rows.append(entry)
    return columns, rows


def parse_company_page(html: str) -> CompanyPage:
    blocks = json_blocks(html)
    details = require_block(blocks, "company_details_data", dict)
    ratios_table = require_block(blocks, "ratios_table", list)
    try:
        ratios = [
            Figure(
                name=clean_text(item["short_name"], 60),
                value=number(item.get("value")),
                unit=_ratio_unit(item["short_name"], str(item.get("unit") or "")),
            )
            for item in ratios_table
        ]
    except (KeyError, TypeError) as exc:
        raise TearsheetError(
            ErrorCode.UPSTREAM_CHANGED, "Tijori's ratio data changed shape."
        ) from exc
    price, price_date = _price(blocks)
    returns = blocks.get("price_returns") if isinstance(blocks.get("price_returns"), dict) else {}
    actions = (
        blocks.get("corporate_actions") if isinstance(blocks.get("corporate_actions"), dict) else {}
    )
    dividends = sorted(
        (
            Dividend(
                ex_date=str(d.get("ex_date") or "")[:10],
                details=clean_text(d.get("event_details"), 120),
            )
            for d in actions.get("Dividend") or []
            if isinstance(d, dict)
        ),
        key=lambda d: d.ex_date,
        reverse=True,
    )[:MAX_DIVIDENDS]
    events = sorted(
        (
            KeyEvent(
                date=str(e.get("chart_date") or "")[:10], event=clean_text(e.get("label"), 240)
            )
            for e in blocks.get("memoryOverviewKeyEvents") or []
            if isinstance(e, dict) and e.get("label")
        ),
        key=lambda e: e.date,
        reverse=True,
    )[:MAX_EVENTS]
    peer_columns, peers = _peers(blocks)
    company_id = blocks.get("companyId", details.get("company_id"))
    return CompanyPage(
        name=clean_text(details.get("company"), 120),
        nse=details.get("symbol") or None,
        status=blocks.get("company_status")
        if isinstance(blocks.get("company_status"), str)
        else details.get("status"),
        classification=details.get("classification"),
        is_banking=bool(details.get("is_banking")),
        company_id=company_id if isinstance(company_id, int) else None,
        price=price,
        price_date=price_date,
        market_cap_crore=number(details.get("mcap_raw")),
        pe=number(details.get("pe")),
        peg=number(details.get("peg")) if details.get("has_peg") is not False else None,
        ratios=ratios,
        averages=_averages(details),
        returns_percent={period: number(returns.get(period)) for period in RETURN_PERIODS},
        dividends=dividends,
        key_events=events,
        peers=peers,
        peer_columns=peer_columns,
        entitlements=_entitlements(blocks),
    )


class MetricInfo(BaseModel):
    metric_id: str
    name: str
    unit: str
    top_level: bool


class _MetricItems(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "li" and values.get("metricid"):
            self.items.append(values)


def operating_metric_list(html: str) -> list[MetricInfo]:
    """List the operating metrics a company page offers. Many companies have none."""
    reader = _MetricItems()
    reader.feed(html)
    return [
        MetricInfo(
            metric_id=item["metricid"],
            name=clean_text(item["title"], 120),
            unit=normalise_unit(item.get("unit", "")),
            top_level=item.get("indent", "0") == "0",
        )
        for item in reader.items
        if item.get("title")
    ]


class MixChart(BaseModel):
    chart_id: str
    title: str
    latest: list[Figure]


class ShareFigure(BaseModel):
    name: str
    value: float | None
    unit: str
    as_of: str | None


class _BusinessMixReader(HTMLParser):
    """Collect revenue-mix charts and market share cards from a company page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.charts: list[dict[str, str]] = []
        self.cards: list[dict[str, str]] = []
        self._capture: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        classes = values.get("class", "").split()
        if "rmix_graph_block" in classes:
            self.charts.append({"title": "", "data": "", "chart_id": ""})
        elif tag == "h4" and self.charts and not self.charts[-1]["title"]:
            self._start("chart_title")
        elif "rmix_pie_chart" in classes and self.charts and "chart-data" in values:
            self.charts[-1]["data"] = values["chart-data"]
            self.charts[-1]["chart_id"] = values.get("chart-id", "")
        elif "market_share_card" in classes:
            self.cards.append(
                {"name": values.get("data-title", ""), "value": "", "unit": "", "asof": ""}
            )
        elif self.cards and tag == "span" and "value" in classes:
            self._start("value")
        elif self.cards and tag == "span" and "unit" in classes:
            self._start("unit")
        elif self.cards and tag == "div" and "asof" in classes:
            self._start("asof")

    def _start(self, field: str) -> None:
        self._capture, self._text = field, []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._capture:
            return
        text = " ".join("".join(self._text).split())
        if self._capture == "chart_title":
            self.charts[-1]["title"] = text
        else:
            self.cards[-1][self._capture] = text
        self._capture = None


def _as_of(text: str) -> str | None:
    found = re.search(r"as of ([A-Za-z]{3}\s*'?\s*\d{2})", text or "")
    return month_label(found.group(1)) if found else None


def parse_business_mix(html: str) -> tuple[list[MixChart], list[ShareFigure]]:
    reader = _BusinessMixReader()
    reader.feed(html)
    charts = []
    for chart in reader.charts:
        try:
            pairs = json.loads(chart["data"]) if chart["data"] else []
        except ValueError:
            continue
        latest = [
            Figure(name=clean_text(name, 80), value=number(share), unit="percent")
            for name, share in pairs
            if isinstance(name, str)
        ]
        if latest:
            charts.append(
                MixChart(
                    chart_id=chart["chart_id"], title=clean_text(chart["title"], 80), latest=latest
                )
            )
    shares = [
        ShareFigure(
            name=clean_text(card["name"].replace(" - Market Share", ""), 120),
            value=number(card["value"]),
            unit=normalise_unit(card["unit"]),
            as_of=_as_of(card["asof"]),
        )
        for card in reader.cards
        if card["name"]
    ]
    return charts, shares
