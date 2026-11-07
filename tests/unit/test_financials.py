"""All figures here are made up. Real Tijori data must never be committed."""

import json

import pytest

from tearsheet.core.errors import ErrorCode, ToolFailure
from tearsheet.sources.tijori.financials import (
    build_statement,
    parse_fund_flow,
    parse_tables,
    unit_for,
)


def row(name, values, children=()):
    return {"name": name, "value": list(values), "sub_section": list(children)}


def table(dates, rows, skip=()):
    return {"report_dates": list(dates), "skip_report_dates": list(skip), "data": list(rows)}


YEARS = ["Mar 2023", "Mar 2024", "Mar 2025"]
WITH_TTM = [*YEARS, "Jun 2025"]


def income(dates=YEARS, **extra):
    n = len(dates)
    return {
        "pl_c_s": table(dates, [row("Sales", range(10, 10 + n))]),
        "pl_s_s": table(dates, [row("Sales", range(20, 20 + n))]),
        **extra,
    }


def test_reads_the_embedded_data_wherever_it_sits_in_the_page():
    html = '<html><script id="fin_tables_data" type="application/json">{"a": 1}</script></html>'
    assert parse_tables(html) == {"a": 1}


@pytest.mark.parametrize(
    "html",
    [
        "<html>nothing here</html>",
        '<script id="fin_tables_data">not json</script>',
        '<script id="fin_tables_data">[1]</script>',
    ],
)
def test_a_missing_or_broken_data_block_is_reported_as_a_changed_site(html):
    with pytest.raises(ToolFailure) as caught:
        parse_tables(html)
    assert caught.value.code is ErrorCode.UPSTREAM_CHANGED


def test_consolidated_is_the_default_and_standalone_can_be_chosen():
    tables = income()
    assert build_statement(tables, statement="income").statement.rows[0].values == [10, 11, 12]
    chosen = build_statement(tables, statement="income", basis="standalone")
    assert chosen.statement.rows[0].values == [20, 21, 22]
    assert chosen.statement.basis == "standalone"


def test_falls_back_to_the_other_basis_and_says_so():
    tables = {"pl_c_s": table(YEARS, [row("Sales", [0, None, 0])]), "pl_s_s": income()["pl_s_s"]}
    parsed = build_statement(tables, statement="income")
    assert parsed.statement.basis == "standalone"
    assert "No consolidated figures" in parsed.warnings[0]


def test_no_data_on_either_basis_is_not_found():
    with pytest.raises(ToolFailure) as caught:
        build_statement({}, statement="cash_flow")
    assert caught.value.code is ErrorCode.NOT_FOUND


def test_keeps_only_the_latest_periods_in_step_with_the_values():
    parsed = build_statement(income(), statement="income", periods=2)
    assert parsed.statement.periods == ["Mar 2024", "Mar 2025"]
    assert parsed.statement.rows[0].values == [11, 12]


def test_marks_a_final_column_that_breaks_the_yearly_pattern_as_ttm():
    parsed = build_statement(income(WITH_TTM), statement="income")
    assert parsed.statement.periods[-1] == "TTM Jun 2025"
    assert parsed.as_of.isoformat() == "2025-06-30"


def test_regular_years_are_not_marked_ttm():
    parsed = build_statement(income(), statement="income")
    assert parsed.statement.periods == YEARS
    assert parsed.as_of.isoformat() == "2025-03-31"


def test_quarterly_columns_are_never_marked_ttm():
    quarters = ["Dec 2024", "Mar 2025", "Jun 2025"]
    tables = {"qt_c": table(quarters, [row("Net Sales", [1, 2, 3])])}
    assert build_statement(tables, statement="quarterly").statement.periods == quarters


def test_warns_when_quarterly_results_are_newer_than_the_ttm_column():
    tables = income(WITH_TTM, qt_c=table(["Jun 2025", "Sep 2025"], [row("Net Sales", [1, 2])]))
    parsed = build_statement(tables, statement="income")
    assert parsed.warnings == [
        "The TTM column ends Jun 2025, but quarterly results run to Sep 2025."
    ]


def test_no_warning_when_the_ttm_column_is_current():
    tables = income(WITH_TTM, qt_c=table(["Mar 2025", "Jun 2025"], [row("Net Sales", [1, 2])]))
    assert build_statement(tables, statement="income").warnings == []


def test_blank_periods_are_dropped_without_a_warning():
    tables = {"cf_c": table(YEARS, [row("Net Cash Flow", [None, 2, 3])], skip=["Mar 2023"])}
    parsed = build_statement(tables, statement="cash_flow")
    assert parsed.statement.periods == ["Mar 2024", "Mar 2025"]
    assert parsed.statement.rows[0].values == [2, 3]
    assert parsed.warnings == []


def test_section_headers_stored_as_zeros_are_not_reported_as_figures():
    children = [row("Quick Ratio", [1.1, 1.2, 1.3])]
    tables = {"fr_c": table(YEARS, [row("Operational Ratios", [0, 0, 0], children)])}
    rows = build_statement(tables, statement="ratios").statement.rows
    assert [r.name for r in rows] == ["Quick Ratio"]
    assert rows[0].group == "Operational Ratios"


def test_a_row_with_real_values_and_children_is_kept():
    children = [row("Current Assets", [4, 5, 6])]
    tables = {"bs_c_s": table(YEARS, [row("Assets", [7, 8, 9], children)])}
    rows = build_statement(tables, statement="balance_sheet").statement.rows
    assert [(r.name, r.group) for r in rows] == [("Assets", None), ("Current Assets", "Assets")]


def test_a_genuine_zero_row_without_children_is_kept():
    tables = {"cf_c": table(YEARS, [row("Dividends Paid", [0, 0, 0]), row("Net Cash", [1, 2, 3])])}
    rows = build_statement(tables, statement="cash_flow").statement.rows
    assert rows[0].values == [0, 0, 0]


def test_a_row_of_the_wrong_length_is_left_out_and_named_never_guessed():
    tables = income()
    tables["pl_c_s"]["data"].append(row("Short Row", [1, 2]))
    parsed = build_statement(tables, statement="income")
    assert [r.name for r in parsed.statement.rows] == ["Sales"]
    assert "Short Row" in parsed.warnings[0]


def test_concise_stays_shallow_and_full_includes_line_items():
    nested = [row("Raw Material", [1, 2, 3], [row("Steel", [4, 5, 6])])]
    tables = {
        "pl_c_s": table(YEARS, [row("Expenses", [7, 8, 9], nested)]),
        "pl_c_d": table(YEARS, [row("Expenses", [7, 8, 9], nested)]),
    }
    concise = build_statement(tables, statement="income").statement.rows
    full = build_statement(tables, statement="income", detail="full").statement.rows
    assert [r.name for r in concise] == ["Expenses"]
    assert [r.name for r in full] == ["Expenses", "Raw Material", "Steel"]


def quarter_table(net_profit, after_tax):
    rows = [row("Profit After Tax", after_tax), row("Net Profit", net_profit)]
    return {"qt_c": table(YEARS, rows)}


def test_a_zero_its_own_statement_disproves_is_blanked_with_a_warning():
    parsed = build_statement(quarter_table([5, 6, 0], [5, 6, 7]), statement="quarterly")
    assert parsed.statement.rows[1].values == [5, 6, None]
    assert parsed.warnings == [
        "Net Profit for Mar 2025 is 0 in Tijori's data, but Profit After Tax is 7.0, "
        "so the figure looks missing and has been left blank."
    ]


def test_the_contradicted_figure_is_never_replaced_with_a_guess():
    rows = build_statement(
        quarter_table([0, 6, 7], [5, 6, 7]), statement="quarterly"
    ).statement.rows
    assert rows[1].values[0] is None
    assert rows[0].values[0] == 5


def test_a_genuine_zero_is_kept():
    parsed = build_statement(quarter_table([5, 0, 7], [5, 0, 7]), statement="quarterly")
    assert parsed.statement.rows[1].values == [5, 0, 7]
    assert parsed.warnings == []


def test_a_real_loss_is_not_mistaken_for_a_gap():
    parsed = build_statement(quarter_table([5, -2, 7], [5, -2, 7]), statement="quarterly")
    assert parsed.statement.rows[1].values == [5, -2, 7]
    assert parsed.warnings == []


def test_values_are_rounded_to_save_tokens():
    tables = {"cf_c": table(["Mar 2025"], [row("Net Cash", [166.58419999999998])])}
    assert build_statement(tables, statement="cash_flow").statement.rows[0].values == [166.5842]


def test_text_numbers_are_read_and_nonsense_becomes_blank():
    tables = {"cf_c": table(YEARS, [row("Net Cash", ["1,234.5", "n/a", None])])}
    values = build_statement(tables, statement="cash_flow").statement.rows[0].values
    assert values == [1234.5, None, None]


def test_an_unreadable_period_label_is_reported_as_a_changed_site():
    tables = {"pl_c_s": table(["FY25", "FY26"], [row("Sales", [1, 2])])}
    with pytest.raises(ToolFailure) as caught:
        build_statement(tables, statement="income")
    assert caught.value.code is ErrorCode.UPSTREAM_CHANGED


def test_a_cash_flow_column_off_the_year_end_is_interim_and_explained():
    tables = {"cf_c": table(["Mar 2024", "Mar 2025", "Sep 2025"], [row("Net Cash", [1, 2, 3])])}
    parsed = build_statement(tables, statement="cash_flow")
    assert parsed.statement.periods[-1] == "Interim Sep 2025"
    assert "doesn't say what period it covers" in parsed.warnings[0]


def test_a_balance_sheet_off_the_year_end_keeps_its_date_because_it_is_a_point_in_time():
    tables = {"bs_c_s": table(["Mar 2025", "Sep 2025"], [row("Assets", [1, 2])])}
    parsed = build_statement(tables, statement="balance_sheet")
    assert parsed.statement.periods == ["Mar 2025", "Sep 2025"]
    assert parsed.warnings == []


def test_row_names_lose_upstream_underscores():
    tables = {"pl_c_s": table(YEARS, [row("Operating_expenses", [1, 2, 3])])}
    assert (
        build_statement(tables, statement="income").statement.rows[0].name == "Operating expenses"
    )


def test_rows_in_a_ratio_section_are_never_assumed_to_be_money():
    children = [row("Gross NPA", [1.1, 1.2, 1.3]), row("CASA Ratio", [30, 31, 32])]
    tables = {"qt_c": table(YEARS, [row("Quarterly Ratios", [0, 0, 0], children)])}
    rows = build_statement(tables, statement="quarterly", detail="full").statement.rows
    assert {r.name: r.unit for r in rows} == {
        "Gross NPA": "as_reported",
        "CASA Ratio": "as_reported",
    }


@pytest.mark.parametrize(
    ("name", "statement", "unit"),
    [
        ("General and Administration Expenses", "income", "crore"),
        ("Provisions and Contingencies", "quarterly", "crore"),
        ("Cost To Income Ratio", "ratios", "as_reported"),
        ("EPS(Rs)", "ratios", "rupees_per_share"),
        ("Free Cash Flow per Share(Rs)", "ratios", "rupees_per_share"),
        ("Debt to Equity", "ratios", "multiple"),
        ("Price to Earnings", "ratios", "multiple"),
        ("Price/Free Cash Flow", "ratios", "multiple"),
        ("Number of Branches", "ratios", "as_reported"),
        ("Sales per Branch (Crs)", "ratios", "crore"),
        ("Sales", "income", "crore"),
        ("OPM (%)", "income", "percent"),
        ("Dividend Payout Ratio(%)", "income", "percent"),
        ("Number of shares(Crs)", "income", "crore_shares"),
        ("EBIT (Crs)", "ratios", "crore"),
        ("ROCE (%)", "ratios", "percent"),
        ("Net Profit Margin", "quarterly", "percent"),
        ("Operating Profit Margin", "quarterly", "percent"),
        ("EPS", "quarterly", "rupees_per_share"),
        ("Adjusted EPS", "ratios", "rupees_per_share"),
        ("Inventory Days", "ratios", "days"),
        ("Days Receivable", "ratios", "days"),
        ("Cash Conversion Cycle", "ratios", "days"),
        ("Quick Ratio", "ratios", "multiple"),
        ("Fixed Asset Turnover", "ratios", "multiple"),
        ("Equity Multiplier", "ratios", "multiple"),
        ("P/E", "ratios", "multiple"),
        ("Price to Book", "ratios", "multiple"),
        ("EV/EBITDA", "ratios", "multiple"),
        ("Something New", "ratios", "as_reported"),
    ],
)
def test_units_come_from_the_row_name(name, statement, unit):
    assert unit_for(name, statement) == unit


def test_the_output_serialises_cleanly():
    parsed = build_statement(income(WITH_TTM), statement="income")
    assert json.loads(parsed.statement.model_dump_json())["periods"][-1] == "TTM Jun 2025"


def test_fund_flow_keeps_windows_groups_and_an_unknown_basis():
    body = {
        "data": [
            {
                "name": "sources",
                "data": {"1yr": [{"name": "Loans", "y": 5}], "3yr": [{"name": "Loans", "y": 9}]},
            },
            {"name": "uses", "data": {"1yr": [{"name": "Capex", "y": 4}]}},
        ]
    }
    parsed = parse_fund_flow(body, periods=5)
    assert parsed.statement.periods == ["Last 1 year", "Last 3 years"]
    assert parsed.statement.basis is None
    assert [(r.group, r.name, r.values) for r in parsed.statement.rows] == [
        ("Sources of funds", "Loans", [5.0, 9.0]),
        ("Uses of funds", "Capex", [4.0, None]),
    ]
    assert "consolidated or standalone" in parsed.warnings[0]
