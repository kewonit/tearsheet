"""All holders and figures here are made up."""

import pytest

from tearsheet.core.errors import ErrorCode, ToolFailure
from tearsheet.sources.tijori.ownership import parse_shareholding

PAGE = """
<table class="peg-sample__table"><tr><td>Base Case</td><td>55-60%</td></tr></table>
<table id="company_detailed">
  <tr><th>in %</th><th>Mar'26</th><th>Jun'26</th><th>Sep'26</th></tr>
  <tr class="row1"><td>Promoter</td><td>70.0</td><td>70.0</td><td>69.5</td></tr>
  <tr class="row2"><td>Indian Promoters</td><td>70.0</td><td>70.0</td><td>69.5</td></tr>
  <tr class="row3"><td>A PERSON</td><td>40.0</td><td>40.0</td><td>39.5</td></tr>
  <tr class="row2"><td>Foreign Promoters</td><td>—</td><td>—</td><td>—</td></tr>
  <tr class="row1"><td>Public Shareholding</td><td>30.0</td><td>30.0</td><td>30.5</td></tr>
  <tr class="row2"><td>Institutions</td><td>2.0</td><td>2.5</td><td>3.0</td></tr>
  <tr class="row1"><td>No. of Shareholders</td><td>1,000</td><td>1,200</td><td>1,500</td></tr>
  <tr class="row1"><td>Wrong Length</td><td>1</td></tr>
</table>"""


def rows(**kwargs):
    return {r.name: r for r in parse_shareholding(PAGE, **kwargs).rows}


def test_reads_the_shareholding_table_not_the_sample_forecast_before_it():
    parsed = parse_shareholding(PAGE, full=False, periods=4)
    assert parsed.periods == ["Mar 2026", "Jun 2026", "Sep 2026"]
    assert "Base Case" not in parsed.model_dump_json()


def test_concise_gives_categories_and_full_adds_named_holders():
    assert "A PERSON" not in rows(full=False, periods=4)
    assert rows(full=True, periods=4)["A PERSON"].group == "Indian Promoters"


def test_groups_follow_the_hierarchy():
    found = rows(full=False, periods=4)
    assert found["Indian Promoters"].group == "Promoter"
    assert found["Institutions"].group == "Public Shareholding"
    assert found["Promoter"].group is None


def test_change_is_computed_on_the_server():
    found = rows(full=False, periods=4)
    assert found["Promoter"].change == -0.5
    assert found["Foreign Promoters"].change is None


def test_the_shareholder_count_is_a_count_not_a_percentage():
    count = rows(full=False, periods=4)["No. of Shareholders"]
    assert (count.unit, count.values[-1]) == ("count", 1500.0)


def test_periods_limit_the_columns():
    parsed = parse_shareholding(PAGE, full=False, periods=2)
    assert parsed.periods == ["Jun 2026", "Sep 2026"]
    assert {r.name: r.values for r in parsed.rows}["Institutions"] == [2.5, 3.0]


def test_rows_of_the_wrong_length_are_left_out():
    assert "Wrong Length" not in rows(full=False, periods=4)


def test_unreadable_period_labels_are_a_changed_site():
    broken = PAGE.replace("Mar'26", "First quarter")
    with pytest.raises(ToolFailure) as caught:
        parse_shareholding(broken, full=False, periods=4)
    assert caught.value.code is ErrorCode.UPSTREAM_CHANGED
