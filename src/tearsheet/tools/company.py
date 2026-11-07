"""Company tools that read Tijori's overview and shareholding pages."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from tearsheet.core.cache import Cache
from tearsheet.core.envelope import Envelope, Source, to_result
from tearsheet.core.errors import ErrorCode, ToolFailure
from tearsheet.sources.tijori.client import BASE_URL, TijoriClient
from tearsheet.sources.tijori.companies import Match, find_one
from tearsheet.sources.tijori.company_page import (
    Average,
    CompanyPage,
    Dividend,
    Figure,
    KeyEvent,
    MetricInfo,
    MixChart,
    ShareFigure,
    operating_metric_list,
    parse_business_mix,
    parse_company_page,
)
from tearsheet.sources.tijori.ownership import Ownership, parse_shareholding
from tearsheet.sources.tijori.pages import date_from_epoch_ms, number
from tearsheet.tools.companies import CompanyQuery, entity_for

PAGE_TTL_S = 3600
SHAREHOLDING_TTL_S = 6 * 3600
METRIC_TTL_S = 6 * 3600
PAID_ONLY = "History needs a paid Tijori plan, so only the latest value is shown."


def month(day: date) -> str:
    return day.strftime("%b %Y")


class CompanyData(BaseModel):
    page: CompanyPage
    metrics: list[MetricInfo]
    revenue_mix: list[MixChart]
    market_share: list[ShareFigure]


async def _fetch(client: TijoriClient, path: str) -> str:
    response = await client.get(path)
    if response.status != 200:
        raise ToolFailure(
            ErrorCode.UPSTREAM_CHANGED, f"Tijori returned {response.status} for {path}."
        )
    return response.text


async def load_company(
    client: TijoriClient, cache: Cache, slug: str
) -> tuple[CompanyData, datetime]:
    entry = cache.get("company_pages", slug)
    if entry is None:
        html = await _fetch(client, f"/company/{slug}/")
        charts, shares = parse_business_mix(html)
        data = CompanyData(
            page=parse_company_page(html),
            metrics=operating_metric_list(html),
            revenue_mix=charts,
            market_share=shares,
        )
        cache.put("company_pages", slug, data.model_dump(mode="json"), ttl_s=PAGE_TTL_S)
        entry = cache.get("company_pages", slug)
    return CompanyData(**entry.value), datetime.fromtimestamp(entry.fetched_at, UTC)


def _source(match: Match, page: str = "") -> list[Source]:
    return [Source(provider="tijori", url=f"{BASE_URL}/company/{match.company.slug}/{page}")]


class Snapshot(BaseModel):
    name: str
    nse: str | None
    bse: str | None
    status: str | None
    classification: str | None
    is_bank: bool
    price_rupees: float | None
    price_date: str | None
    market_cap_crore: float | None
    pe: float | None
    peg: float | None
    key_figures: list[Figure]
    averages: list[Average]
    returns_percent: dict[str, float | None]
    dividends: list[Dividend]
    key_events: list[KeyEvent]
    plan: str


def build_snapshot(match: Match, data: CompanyData) -> tuple[Snapshot, list[str]]:
    page = data.page
    warnings = [
        "Prices on Tijori are delayed, not live.",
        "Key events are Tijori's own summaries, so treat them as source material.",
    ]
    if page.status and page.status.lower() != "active":
        warnings.insert(0, f"Tijori lists this company's status as {page.status}.")
    snapshot = Snapshot(
        name=page.name,
        nse=page.nse or match.company.nse,
        bse=match.company.bse,
        status=page.status,
        classification=page.classification,
        is_bank=page.is_banking,
        price_rupees=page.price,
        price_date=page.price_date.isoformat() if page.price_date else None,
        market_cap_crore=page.market_cap_crore,
        pe=page.pe,
        peg=page.peg,
        key_figures=page.ratios,
        averages=page.averages,
        returns_percent=page.returns_percent,
        dividends=page.dividends,
        key_events=page.key_events,
        plan=page.entitlements.plan_tier,
    )
    return snapshot, warnings


class MetricSeries(BaseModel):
    name: str
    unit: str
    latest_period: str | None
    latest_value: float | None
    history: list[tuple[str, float | None]] | None


class OperatingMetrics(BaseModel):
    metrics: list[MetricSeries]
    available: int
    history_included: bool


async def _metric_points(
    client: TijoriClient, cache: Cache, company_id: int, metric: MetricInfo, history: bool
) -> list[tuple[str, float | None]]:
    """Fetch one metric. Without paid access only the latest point is kept, even in the cache."""
    key = f"{company_id}:{metric.metric_id}:{'all' if history else 'latest'}:v2"
    entry = cache.get("operating_metrics", key)
    if entry is not None:
        return [tuple(point) for point in entry.value]
    response = await client.get(f"/api/v1/ind/company_op_metrics/{company_id}/{metric.metric_id}/")
    body = response.json()
    series = body.get("data") if isinstance(body, dict) else None
    if not isinstance(series, list):
        raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's metric data changed shape.")
    dated = []
    for point in series:
        if isinstance(point, list) and len(point) == 2:
            day = date_from_epoch_ms(point[0])
            if day is not None:
                dated.append((day, number(point[1])))
    # Tijori's chart dates mark a month, with a day that varies for no reason,
    # such as 1 March one year and 31 March the next. Sort by the real date,
    # then label by month.
    dated.sort(key=lambda item: item[0])
    points = [(month(day), value) for day, value in dated]
    kept = points if history else points[-1:]
    cache.put("operating_metrics", key, kept, ttl_s=METRIC_TTL_S)
    return kept


class BusinessMix(BaseModel):
    revenue_mix: list[MixChart]
    market_share: list[ShareFigure]
    revenue_mix_history: dict[str, list[tuple[str, dict[str, float | None]]]] | None


def register(server: MCPServer, *, client: TijoriClient, cache: Cache, read_only: Any) -> None:
    tool: Callable = server.tool(annotations=read_only)

    @tool
    async def company_snapshot(company: CompanyQuery) -> Envelope[Snapshot]:
        """Get a one-call overview of a listed Indian company.

        Returns identifiers, status, size class, delayed price, market cap, P/E,
        PEG, key ratios with their units, multi-year ROE and margin averages,
        price changes up to one year, recent dividends and dated key events.
        Use it first when asked about a company in general. It contains facts
        only: Tijori's own opinions and forecasts are deliberately left out.
        Longer-term returns are omitted because their basis isn't stated.
        """
        match = await find_one(client, cache, company)
        data, fetched_at = await load_company(client, cache, match.company.slug)
        snapshot, warnings = build_snapshot(match, data)
        return to_result(
            Envelope[Snapshot](
                data=snapshot,
                entity=entity_for(match.company),
                as_of=data.page.price_date,
                retrieved_at=fetched_at,
                sources=_source(match),
                warnings=warnings,
            )
        )

    @tool
    async def get_ownership(
        company: CompanyQuery,
        detail: Literal["concise", "full"] = "concise",
        periods: Annotated[int, Field(ge=1, le=12)] = 4,
    ) -> Envelope[Ownership]:
        """Get a company's shareholding pattern by quarter.

        Returns promoter, institutional and public holdings in percent, the
        number of shareholders, and each row's change over the last period.
        Concise gives categories. Full adds the named holders that companies
        must disclose above 1%. Use it for questions about who owns a company
        or how ownership is changing.
        """
        match = await find_one(client, cache, company)
        slug = match.company.slug
        entry = cache.get("shareholding_pages", slug)
        if entry is None:
            html = await _fetch(client, f"/company/{slug}/shareholding/")
            cache.put("shareholding_pages", slug, html, ttl_s=SHAREHOLDING_TTL_S)
            entry = cache.get("shareholding_pages", slug)
        ownership = parse_shareholding(entry.value, full=detail == "full", periods=periods)
        return to_result(
            Envelope[Ownership](
                data=ownership,
                entity=entity_for(match.company),
                retrieved_at=datetime.fromtimestamp(entry.fetched_at, UTC),
                sources=_source(match, "shareholding/"),
            )
        )

    @tool
    async def get_operating_metrics(
        company: CompanyQuery,
        metric: Annotated[str | None, Field(max_length=100)] = None,
        limit: Annotated[int, Field(ge=1, le=20)] = 8,
    ) -> Envelope[OperatingMetrics]:
        """Get a company's operating metrics, such as capacity, volumes or deal wins.

        These are company-specific KPIs beyond the financial statements. Many
        smaller companies have none, which returns an empty list. Use metric to
        filter by part of a name. Each metric has its own unit. With Tijori's
        free plan only the latest value is available, matching what Tijori's
        own pages show, and history needs a paid plan.
        """
        match = await find_one(client, cache, company)
        data, _ = await load_company(client, cache, match.company.slug)
        available = data.metrics
        if metric:
            available = [m for m in available if metric.lower() in m.name.lower()]
        chosen = [m for m in available if m.top_level][:limit] or available[:limit]
        history = data.page.entitlements.metrics_history
        series = []
        if chosen and data.page.company_id is None:
            raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's page has no company id.")
        for info in chosen:
            points = await _metric_points(client, cache, data.page.company_id, info, history)
            latest = points[-1] if points else (None, None)
            series.append(
                MetricSeries(
                    name=info.name,
                    unit=info.unit,
                    latest_period=latest[0],
                    latest_value=latest[1],
                    history=points if history else None,
                )
            )
        warnings = []
        if not data.metrics:
            warnings.append("Tijori has no operating metrics for this company.")
        elif not history:
            warnings.append(PAID_ONLY)
        return to_result(
            Envelope[OperatingMetrics](
                data=OperatingMetrics(
                    metrics=series, available=len(data.metrics), history_included=history
                ),
                entity=entity_for(match.company),
                sources=_source(match),
                warnings=warnings,
            )
        )

    @tool
    async def get_business_mix(company: CompanyQuery) -> Envelope[BusinessMix]:
        """Get how a company's business splits, and its market shares.

        Returns the latest revenue split by product, geography, segment or
        other breakdowns Tijori tracks, each in percent, plus market share
        figures. Every market share has its own as-of date, and some are years
        old, so always check it. History needs a paid Tijori plan.
        """
        match = await find_one(client, cache, company)
        data, fetched_at = await load_company(client, cache, match.company.slug)
        warnings = []
        history = None
        if data.page.entitlements.revenue_mix_history:
            history = await _revenue_history(client, cache, data.revenue_mix)
        elif data.revenue_mix:
            warnings.append(
                "Revenue mix history needs a paid Tijori plan, so only the latest split is shown."
            )
        if not data.revenue_mix and not data.market_share:
            warnings.append("Tijori has no business mix or market share data for this company.")
        stale = [
            s.name for s in data.market_share if s.as_of and int(s.as_of[-4:]) < fetched_at.year - 1
        ]
        if stale:
            warnings.append(
                f"Some market share figures are more than a year old: {', '.join(stale)}."
            )
        return to_result(
            Envelope[BusinessMix](
                data=BusinessMix(
                    revenue_mix=data.revenue_mix,
                    market_share=data.market_share,
                    revenue_mix_history=history,
                ),
                entity=entity_for(match.company),
                retrieved_at=fetched_at,
                sources=_source(match),
                warnings=warnings,
            )
        )


async def _revenue_history(
    client: TijoriClient, cache: Cache, charts: list[MixChart]
) -> dict[str, list[tuple[str, dict[str, float | None]]]]:
    """Only called when the session's plan unlocks revenue mix history."""
    import json

    history: dict[str, list[tuple[str, dict[str, float | None]]]] = {}
    for chart in charts:
        response = await client.get(f"/api/rmix/historic/graph/{chart.chart_id}")
        body = response.json()
        by_date: dict[date, dict[str, float | None]] = {}
        for part in (body.get("context") if isinstance(body, dict) else None) or []:
            try:
                points = json.loads(part.get("graphdata") or "[]")
            except ValueError:
                continue
            for stamp, value in points:
                day = date_from_epoch_ms(stamp)
                if day is not None:
                    by_date.setdefault(day, {})[str(part.get("fieldname"))] = number(value)
        history[chart.title] = [(month(day), shares) for day, shares in sorted(by_date.items())]
    return history
