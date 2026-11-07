from datetime import date

import pytest

from tearsheet.core.errors import ErrorCode, ToolFailure
from tearsheet.sources.tijori.pages import (
    clean_text,
    date_from_epoch_ms,
    json_blocks,
    month_label,
    number,
    table_rows,
)


def test_reads_named_json_blocks_and_skips_broken_ones():
    html = (
        '<script type="application/json" id="good">{"a": 1}</script>'
        '<script id="also" type="application/json">[1, 2]</script>'
        '<script type="application/json" id="broken">{nope</script>'
        '<script id="not-json">{"b": 2}</script>'
    )
    assert json_blocks(html) == {"good": {"a": 1}, "also": [1, 2]}


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1,23,456.7", 123456.7),
        ("14.62%", 14.62),
        ("₹2,468", 2468.0),
        ("-3.5", -3.5),
        ("—", None),
        ("–", None),
        ("", None),
        ("n/a", None),
        (None, None),
        (True, None),
        (12, 12.0),
    ],
)
def test_reads_figures_as_tijori_writes_them(text, value):
    assert number(text) == value


def test_chart_times_are_read_as_indian_dates():
    # 2026-03-31 18:30 UTC is midnight on 1 April in India.
    assert date_from_epoch_ms(1774981800000) == date(2026, 4, 1)
    assert date_from_epoch_ms("x") is None


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("Jun'26", "Jun 2026"),
        ("Jun 26", "Jun 2026"),
        ("Mar26", "Mar 2026"),
        ("FY26", None),
        ("", None),
    ],
)
def test_month_labels(text, label):
    assert month_label(text) == label


def test_clean_text_drops_control_characters_and_caps_length():
    assert clean_text("a‮b\x1b[31m  c\n d") == "ab[31m c d"
    assert clean_text("x" * 50, limit=10) == "x" * 9 + "…"


def test_table_rows_finds_its_table_by_id_ignoring_others_and_nested_tables():
    html = (
        '<table id="decoy"><tr><td>wrong</td></tr></table>'
        '<table id="wanted">'
        '<tr class="row1" parent="1"><th>in %</th><th>Jun\'26</th></tr>'
        "<tr><td>Promoter <b>group</b></td>"
        "<td><table><tr><td>inner</td></tr></table>50</td></tr>"
        "<tr></tr>"
        "</table>"
    )
    rows = table_rows(html, "wanted")
    assert [r.cells for r in rows] == [["in %", "Jun'26"], ["Promoter group", "50"]]
    assert rows[0].attrs["class"] == "row1"


def test_a_missing_table_is_a_changed_site():
    with pytest.raises(ToolFailure) as caught:
        table_rows("<table id='other'></table>", "wanted")
    assert caught.value.code is ErrorCode.UPSTREAM_CHANGED
