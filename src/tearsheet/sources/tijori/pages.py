"""Shared parsing for Tijori's HTML pages, using only the standard library.

Pages carry most of their data as JSON in named script tags, plus a few HTML
tables. Blocks that describe the signed-in user are read only to work out what
their plan allows, never returned.
"""

import json
import re
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any

from pydantic import BaseModel

from tearsheet.core.errors import ErrorCode, TearsheetError

_JSON_TAG = re.compile(
    r"""<script(?=[^>]*type=["']application/json["'])(?=[^>]*\bid=["']([^"']+)["'])[^>]*>(.*?)</script>""",
    re.DOTALL,
)
_BLANKS = {"", "—", "–", "-", "NA", "N/A", "null"}
IST = timedelta(hours=5, minutes=30)


def json_blocks(html: str) -> dict[str, Any]:
    """Return every named JSON block on a page. Unparseable blocks are skipped."""
    blocks = {}
    for name, body in _JSON_TAG.findall(html):
        try:
            blocks[name] = json.loads(body)
        except ValueError:
            continue
    return blocks


def require_block(blocks: dict[str, Any], name: str, kind: type) -> Any:
    value = blocks.get(name)
    if not isinstance(value, kind):
        raise TearsheetError(
            ErrorCode.UPSTREAM_CHANGED, f"Tijori's page no longer has its {name} data."
        )
    return value


def number(text: Any) -> float | None:
    """Read a figure as Tijori writes it, such as '1,23,456.7', '14.62%' or '—'."""
    if isinstance(text, bool) or text is None:
        return None
    if isinstance(text, int | float):
        return round(float(text), 4)
    cleaned = str(text).strip().replace(",", "").replace("%", "").replace("₹", "").strip()
    if cleaned in _BLANKS:
        return None
    try:
        return round(float(cleaned), 4)
    except ValueError:
        return None


def date_from_epoch_ms(value: Any) -> date | None:
    """Tijori's charts use milliseconds since the epoch, drawn in Indian time."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return (datetime.fromtimestamp(value / 1000, UTC) + IST).date()


def month_label(text: str) -> str | None:
    """Turn labels like "Jun'26", "Jun 26" or "Mar26" into "Jun 2026"."""
    found = re.fullmatch(r"\s*([A-Za-z]{3})\s*'?\s*(\d{2})\s*", text or "")
    if found is None:
        return None
    try:
        parsed = datetime.strptime(f"{found.group(1).title()} {found.group(2)}", "%b %y")
    except ValueError:
        return None
    return parsed.strftime("%b %Y")


def clean_text(text: Any, limit: int = 300) -> str:
    """Collapse whitespace, drop control characters and cap length.

    Text from pages is third-party material, so tools pass it on as data only.
    """
    flat = " ".join(str(text or "").split())
    flat = "".join(ch for ch in flat if ch.isprintable())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


class Row(BaseModel):
    cells: list[str]
    attrs: dict[str, str]


class _TableReader(HTMLParser):
    def __init__(self, table_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.depth = 0
        self.rows: list[Row] = []
        self._cell: list[str] | None = None
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "table":
            if self.depth:
                self.depth += 1
            elif values.get("id") == self.table_id:
                self.depth, self.found = 1, True
            return
        # Only the table's own rows count. Nested tables are skipped entirely.
        if self.depth != 1:
            return
        if tag == "tr":
            self.rows.append(Row(cells=[], attrs=values))
        elif tag in ("td", "th") and self.rows:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if not self.depth:
            return
        if tag == "table":
            self.depth -= 1
        elif self.depth == 1 and tag in ("td", "th") and self._cell is not None:
            self.rows[-1].cells.append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self.depth == 1 and self._cell is not None:
            self._cell.append(data)


def table_rows(html: str, table_id: str) -> list[Row]:
    """Return the rows of the table with this id, or raise if it's gone."""
    reader = _TableReader(table_id)
    reader.feed(html)
    if not reader.found:
        raise TearsheetError(
            ErrorCode.UPSTREAM_CHANGED, f"Tijori's page no longer has its {table_id} table."
        )
    return [row for row in reader.rows if row.cells]
