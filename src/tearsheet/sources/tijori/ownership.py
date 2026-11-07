"""Read the shareholding pattern from a company's shareholding page."""

from pydantic import BaseModel

from tearsheet.core.errors import ErrorCode, ToolFailure
from tearsheet.sources.tijori.pages import clean_text, month_label, number, table_rows

# The page also holds sample forecast tables for another product, so the
# shareholding table is always found by its id, never by position.
TABLE_ID = "company_detailed"
_COUNT_ROWS = {"no. of shareholders"}


class Holding(BaseModel):
    name: str
    group: str | None
    level: int
    unit: str
    values: list[float | None]
    change: float | None


class Ownership(BaseModel):
    periods: list[str]
    rows: list[Holding]


def _level(classes: str) -> int:
    for level in (1, 2, 3):
        if f"row{level}" in classes.split():
            return level
    return 1


def parse_shareholding(html: str, *, full: bool, periods: int) -> Ownership:
    """Categories by default. Full adds named holders, which companies disclose above 1%."""
    rows = table_rows(html, TABLE_ID)
    if len(rows) < 2:
        raise ToolFailure(ErrorCode.UPSTREAM_CHANGED, "Tijori's shareholding table is empty.")
    labels = [month_label(cell) for cell in rows[0].cells[1:]]
    if not labels or None in labels:
        raise ToolFailure(
            ErrorCode.UPSTREAM_CHANGED, "Tijori's shareholding periods aren't month labels."
        )
    keep = slice(-periods, None)
    parents: dict[int, str] = {}
    holdings = []
    for row in rows[1:]:
        level = _level(row.attrs.get("class", ""))
        name = clean_text(row.cells[0], 120)
        parents[level] = name
        if level == 3 and not full:
            continue
        values = [number(cell) for cell in row.cells[1:]]
        if len(values) != len(labels):
            continue
        shown = values[keep]
        latest, previous = (shown[-1], shown[-2]) if len(shown) > 1 else (None, None)
        change = (
            round(latest - previous, 4) if latest is not None and previous is not None else None
        )
        holdings.append(
            Holding(
                name=name,
                group=parents.get(level - 1) if level > 1 else None,
                level=level,
                unit="count" if name.lower() in _COUNT_ROWS else "percent",
                values=shown,
                change=change,
            )
        )
    return Ownership(periods=[label for label in labels if label][keep], rows=holdings)
