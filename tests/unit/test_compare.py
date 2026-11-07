from tearsheet.tools.compare import growth_figures
from tests.unit.test_financials import row, table


def income(dates, sales, profit):
    return {"pl_c_s": table(dates, [row("Sales", sales), row("Net Profit", profit)])}


def test_growth_uses_annual_columns_never_ttm():
    tables = income(
        ["Mar 2022", "Mar 2023", "Mar 2024", "Mar 2025", "Jun 2025"],
        [100, 110, 121, 133.1, 999],
        [10, 11, 12, 15, 999],
    )
    year, figures = growth_figures(tables)
    assert year == "Mar 2025"
    assert figures == {
        "revenue_latest_year_crore": 133.1,
        "revenue_growth_percent": 10.0,
        "net_profit_growth_percent": 25.0,
        "revenue_cagr_3y_percent": 10.0,
    }


def test_growth_from_a_loss_is_blank():
    _, figures = growth_figures(income(["Mar 2024", "Mar 2025"], [100, 110], [-5, 10]))
    assert figures["net_profit_growth_percent"] is None
    assert figures["revenue_cagr_3y_percent"] is None


def test_banks_use_total_income_as_revenue():
    tables = {"pl_c_s": table(["Mar 2024", "Mar 2025"], [row("Total Income", [100, 120])])}
    assert growth_figures(tables)[1]["revenue_growth_percent"] == 20.0
