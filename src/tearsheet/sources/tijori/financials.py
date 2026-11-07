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

from tearsheet.core.errors import ErrorCode, TearsheetError

Statement = Literal["income", "balance_sheet", "cash_flow", "quarterly", "ratios"]
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
_MULTIPLE_NAMES = re.compile(r"ratio|turnover|multiplier|^p/e$|price to book|ev/ebitda", re.I)


class FinancialRow(BaseModel):
    name: str
    group: str | None = None
    unit: str
    values: list[float | None]


class FinancialStatement(BaseModel):
    statement: Statement
    basis: Basis
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
        raise TearsheetError(
            ErrorCode.UPSTREAM_CHANGED, "Tijori's financials page no longer embeds its data."
        )
    try:
        tables = json.loads(found.group(1))
    except ValueError as exc:
        raise TearsheetError(
            ErrorCode.UPSTREAM_CHANGED, "Tijori's embedded financial data isn't valid."
        ) from exc
    if not isinstance(tables, dict):
        raise TearsheetError(ErrorCode.UPSTREAM_CHANGED, "Tijori's financial data changed shape.")
    return tables


def _table_key(statement: str, basis: str, detail: str) -> str:
    key = f"{_PREFIX[statement]}_{basis[0]}"
    if statement in _HAS_SUMMARY_VIEW:
        key += "_s" if detail == "concise" else "_d"
    return key


def unit_for(name: str, statement: str) -> str:
    """Work out a row's unit from its name.

    Ratio tables have no default unit, so an unrecognised row there is marked
    as_reported rather than assumed to be money.
    """
    if "%" in name or "margin" in name.lower():
        return "percent"
    if "number of shares" in name.lower():
        return "crore_shares"
    if "(crs)" in name.lower():
        return "crore"
    if "eps" in name.lower().split():
        return "rupees_per_share"
    if re.search(r"\bdays\b|\bcycle\b", name, re.I):
        return "days"
    if _MULTIPLE_NAMES.search(name):
        return "multiple"
    return "as_reported" if statement == "ratios" else "crore"


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
        raise TearsheetError(
            ErrorCode.UPSTREAM_CHANGED, f"Tijori's period label {label!r} isn't a month and year."
        ) from exc


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def _label_periods(dates: list[str], statement: str) -> list[str]:
    """Mark a final income column that doesn't follow the yearly pattern as TTM."""
    labels = list(dates)
    if statement != "income" or len(dates) < 2:
        return labels
    if _months_between(_parse_month(dates[-2]), _parse_month(dates[-1])) != 12:
        labels[-1] = f"TTM {dates[-1]}"
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
    table = tables.get(_table_key(statement, basis, detail))
    if not _has_figures(table):
        other: Basis = "standalone" if basis == "consolidated" else "consolidated"
        table = tables.get(_table_key(statement, other, detail))
        if not _has_figures(table):
            raise TearsheetError(
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
    rows = [
        FinancialRow(
            name=row["name"],
            group=group,
            unit=unit_for(row["name"], statement),
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
