"""Read company financials from the data Tijori embeds in its pages.

Tijori's financials page carries every statement as JSON in a script tag, so
nothing needs rendering. That data has traps that would otherwise produce
confident wrong numbers:

- The last income column can be trailing twelve months under a plain date.
- Section headers are stored as rows of zeros.
- Rows mix crore, percentages, days, multiples and rupees per share.
- A row can have fewer values than there are periods.
- Periods before a company had subsidiaries are blank in consolidated tables.
- The trailing twelve months can lag the latest quarterly results.
- A figure missing from a recent quarter can be stored as 0, beside rows that
  prove it isn't.
"""

import calendar
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from tearsheet.core.errors import ErrorCode, ToolFailure

Statement = Literal["income", "balance_sheet", "cash_flow", "quarterly", "ratios", "fund_flow"]
Basis = Literal["consolidated", "standalone"]
Detail = Literal["concise", "full"]

_DATA_TAG = re.compile(
    r"""<script[^>]*\bid=["']fin_tables_data["'][^>]*>(.*?)</script>""", re.DOTALL
)
_PREFIX: dict[str, str] = {
    "income": "pl",
    "balance_sheet": "bs",
    "cash_flow": "cf",
    "quarterly": "qt",
    "ratios": "fr",
}
_HAS_SUMMARY_VIEW = {"income", "balance_sheet"}
# Concise answers stop at this depth. These statements nest their real rows.
_CONCISE_DEPTH = {"balance_sheet": 1, "ratios": 1}
# A zero in the first row can't be right if the second row is non-zero.
_CROSS_CHECKS = {
    "income": (("Net Profit", "Profit Before Tax"),),
    "quarterly": (("Net Profit", "Profit After Tax"), ("PBDT", "Profit Before Tax")),
}
# Only these are known to be multiples. Tijori calls some percentages "ratios",
# such as CASA Ratio, so a name that merely sounds like a ratio isn't enough.
_MULTIPLES = {
    "asset turnover ratio",
    "current ratio",
    "debt to equity",
    "debt to equity ratio",
    "equity multiplier",
    "ev/ebitda",
    "fixed asset turnover",
    "interest coverage ratio",
    "p/e",
    "price to book",
    "price to book value",
    "price to earnings",
    "price/free cash flow",
    "quick ratio",
}


class FinancialRow(BaseModel):
    name: str
    group: str | None = None
    unit: str
    values: list[float | None]


class FinancialStatement(BaseModel):
    statement: Statement
    basis: Basis | None
    periods: list[str]
    rows: list[FinancialRow]


@dataclass(frozen=True)
class ParsedStatement:
    statement: FinancialStatement
    as_of: date | None
    warnings: list[str]


def parse_tables(html: str) -> dict[str, Any]:
    """Pull the embedded tables out of a financials page."""
    found = _DATA_TAG.search(html)
    if found is None:
        raise ToolFailure(
            ErrorCode.UPSTREAM_CHANGED, "Tijori's financials page no longer embeds its data."
        )
    try:
        tables = json.loads(found.group(1))
    except ValueError as exc:
        raise ToolFailure(
            ErrorCode.UPSTREAM_CHANGED, "Tijori's embedded financial data isn't valid."
        ) from exc
    if not isinstance(tables, dict):
        raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's financial data changed shape.")
    return tables


def _table_key(statement: str, basis: str, detail: str) -> str:
    key = f"{_PREFIX[statement]}_{basis[0]}"
    if statement in _HAS_SUMMARY_VIEW:
        key += "_s" if detail == "concise" else "_d"
    return key


def unit_for(name: str, statement: str, group: str | None = None) -> str:
    """Work out a row's unit from its name.

    Only rows outside ratio sections default to crore. Anything unrecognised
    inside one is marked as_reported rather than given a unit it may not have.
    """
    lowered = name.lower()
    if "%" in name or "margin" in lowered:
        return "percent"
    if "number of shares" in lowered:
        return "crore_shares"
    if "(crs)" in lowered:
        return "crore"
    if re.search(r"\beps\b|per share", lowered):
        return "rupees_per_share"
    if re.search(r"\bdays\b|\bcycle\b", lowered):
        return "days"
    if lowered in _MULTIPLES:
        return "multiple"
    in_ratio_section = statement == "ratios" or "ratio" in (group or "").lower()
    return "as_reported" if in_ratio_section else "crore"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return round(float(value), 4)
    try:
        return round(float(str(value).replace(",", "").replace("%", "").strip()), 4)
    except ValueError:
        return None


def _is_header(row: dict[str, Any]) -> bool:
    """Section headers have children and only zeros or blanks of their own."""
    return bool(row.get("sub_section")) and not any(_number(v) for v in row.get("value") or [])


def _parse_month(label: str) -> date:
    try:
        return datetime.strptime(label, "%b %Y").date()
    except ValueError as exc:
        raise ToolFailure(
            ErrorCode.UPSTREAM_CHANGED, f"Tijori's period label {label!r} isn't a month and year."
        ) from exc


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def _label_periods(dates: list[str], statement: str) -> list[str]:
    """Mark a final column that breaks the yearly pattern.

    Income columns like this are trailing twelve months, which Tijori's pages
    state and its quarterly figures confirm. Cash flow columns look similar, but
    Tijori doesn't say what they cover, so they only get called interim.
    """
    labels = list(dates)
    prefix = {"income": "TTM", "cash_flow": "Interim"}.get(statement)
    if prefix is None or len(dates) < 2:
        return labels
    if _months_between(_parse_month(dates[-2]), _parse_month(dates[-1])) != 12:
        labels[-1] = f"{prefix} {dates[-1]}"
    return labels


def _month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _flatten(
    rows: list[dict[str, Any]],
    *,
    statement: str,
    period_count: int,
    max_depth: int | None,
    depth: int = 0,
    group: str | None = None,
    skipped: list[str],
) -> list[tuple[str | None, dict[str, Any]]]:
    flat = []
    for row in rows:
        header = _is_header(row)
        if not header:
            if len(row.get("value") or []) == period_count:
                flat.append((group, row))
            else:
                skipped.append(row.get("name", "unnamed"))
        if max_depth is None or depth < max_depth:
            flat += _flatten(
                row.get("sub_section") or [],
                statement=statement,
                period_count=period_count,
                max_depth=max_depth,
                depth=depth + 1,
                group=row.get("name") or group,
                skipped=skipped,
            )
    return flat


def _has_figures(table: dict[str, Any] | None) -> bool:
    if not table or not table.get("report_dates"):
        return False

    def any_figure(rows: list[dict[str, Any]]) -> bool:
        return any(
            any(_number(v) for v in row.get("value") or [])
            or any_figure(row.get("sub_section") or [])
            for row in rows
        )

    return any_figure(table.get("data") or [])


def _lagging_ttm_warning(tables: dict[str, Any], basis: str, ttm_date: str) -> list[str]:
    quarters = tables.get(_table_key("quarterly", basis, "concise")) or {}
    latest = (quarters.get("report_dates") or [ttm_date])[-1]
    if _parse_month(latest) > _parse_month(ttm_date):
        return [f"The TTM column ends {ttm_date}, but quarterly results run to {latest}."]
    return []


def _blank_contradicted_zeros(
    rows: list[FinancialRow], labels: list[str], statement: str
) -> list[str]:
    """Blank zeros that their own statement disproves, rather than guess the real value."""
    by_name = {row.name: row for row in rows}
    warnings = []
    for name, reference in _CROSS_CHECKS.get(statement, ()):
        row, other = by_name.get(name), by_name.get(reference)
        if row is None or other is None:
            continue
        for index, (value, known) in enumerate(zip(row.values, other.values, strict=True)):
            if value == 0 and known:
                row.values[index] = None
                warnings.append(
                    f"{name} for {labels[index]} is 0 in Tijori's data, but {reference} is "
                    f"{known}, so the figure looks missing and has been left blank."
                )
    return warnings


def build_statement(
    tables: dict[str, Any],
    *,
    statement: Statement,
    basis: Basis = "consolidated",
    detail: Detail = "concise",
    periods: int = 5,
) -> ParsedStatement:
    """Turn embedded tables into a statement with labelled periods and units."""
    warnings = []
    if statement == "fund_flow":
        raise ValueError("fund flow comes from its own endpoint; use parse_fund_flow")
    table = tables.get(_table_key(statement, basis, detail))
    if not _has_figures(table):
        other: Basis = "standalone" if basis == "consolidated" else "consolidated"
        table = tables.get(_table_key(statement, other, detail))
        if not _has_figures(table):
            raise ToolFailure(
                ErrorCode.NOT_FOUND, f"Tijori has no {statement.replace('_', ' ')} data for this."
            )
        warnings.append(f"No {basis} figures exist, so these are {other}.")
        basis = other

    dates: list[str] = table["report_dates"]
    # Tijori lists periods with no figures here, such as years before a subsidiary existed.
    blank = set(table.get("skip_report_dates") or [])
    keep = [index for index, label in enumerate(dates) if label not in blank]
    skipped: list[str] = []
    max_depth = _CONCISE_DEPTH.get(statement, 0) if detail == "concise" else None
    flat = _flatten(
        table.get("data") or [],
        statement=statement,
        period_count=len(dates),
        max_depth=max_depth,
        skipped=skipped,
    )
    if skipped:
        warnings.append(
            f"Left out rows with incomplete periods: {', '.join(sorted(set(skipped)))}."
        )

    all_labels = _label_periods(dates, statement)
    labels = [all_labels[index] for index in keep][-periods:]
    if labels[-1].startswith("TTM "):
        warnings += _lagging_ttm_warning(tables, basis, dates[-1])
    if labels[-1].startswith("Interim "):
        warnings.append(
            f"The {dates[-1]} column isn't a financial year end, and Tijori doesn't "
            "say what period it covers, so don't compare it directly with annual columns."
        )
    rows = [
        FinancialRow(
            name=row["name"].replace("_", " "),
            group=group,
            unit=unit_for(row["name"], statement, group),
            values=[_number(row["value"][index]) for index in keep][-periods:],
        )
        for group, row in flat
    ]
    warnings += _blank_contradicted_zeros(rows, labels, statement)
    return ParsedStatement(
        FinancialStatement(statement=statement, basis=basis, periods=labels, rows=rows),
        _month_end(_parse_month(dates[-1])),
        warnings,
    )


FUND_FLOW_WINDOWS = {
    "1yr": "Last 1 year",
    "3yr": "Last 3 years",
    "5yr": "Last 5 years",
    "7yr": "Last 7 years",
    "10yr": "Last 10 years",
}
_FUND_FLOW_GROUPS = {"sources": "Sources of funds", "uses": "Uses of funds"}


def parse_fund_flow(body: Any, periods: int) -> ParsedStatement:
    """Where a company's money came from and went, over trailing windows.

    Tijori doesn't say whether these figures are consolidated or standalone,
    so the basis is left blank rather than guessed.
    """
    parts = body.get("data") if isinstance(body, dict) else None
    if not isinstance(parts, list) or not parts:
        raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's fund flow data changed shape.")
    windows = [w for w in FUND_FLOW_WINDOWS if any(w in (p.get("data") or {}) for p in parts)][
        :periods
    ]
    rows = []
    for part in parts:
        group = _FUND_FLOW_GROUPS.get(str(part.get("name")).lower(), str(part.get("name")))
        series = part.get("data") or {}
        names: list[str] = []
        for window in windows:
            for item in series.get(window) or []:
                if item.get("name") not in names:
                    names.append(item.get("name"))
        for name in names:
            values = []
            for window in windows:
                match = next((i for i in series.get(window) or [] if i.get("name") == name), None)
                values.append(_number(match.get("y")) if match else None)
            rows.append(FinancialRow(name=str(name), group=group, unit="crore", values=values))
    if not rows:
        raise ToolFailure(ErrorCode.NOT_FOUND, "Tijori has no fund flow data for this company.")
    return ParsedStatement(
        FinancialStatement(
            statement="fund_flow",
            basis=None,
            periods=[FUND_FLOW_WINDOWS[w] for w in windows],
            rows=rows,
        ),
        None,
        ["Tijori doesn't say whether fund flow is consolidated or standalone."],
    )
