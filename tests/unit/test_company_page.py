"""All companies and figures here are made up."""

import json

import pytest

from tearsheet.core.errors import ErrorCode, ToolFailure
from tearsheet.sources.tijori.company_page import (
    operating_metric_list,
    parse_business_mix,
    parse_company_page,
)


def block(name, value):
    return f'<script type="application/json" id="{name}">{json.dumps(value)}</script>'


def page(*, locks=None, plan=None, extra=""):
    details = {
        "company": "Acme Fine-Chem Ltd.",
        "symbol": "ACMEFINE",
        "classification": "Small",
        "is_banking": False,
        "company_id": 77,
        "mcap_raw": 1500.0,
        "pe": 20.5,
        "has_peg": True,
        "peg": 1.5,
        "peg_summary": "TIJORI OPINION: made-up commentary for this test",
        "quick_look": {
            "data": [{"name": "Flags", "factories": [{"sentence": "TIJORI JUDGEMENT"}]}],
            "table_data": [
                {
                    "name": "ROE",
                    "data": [
                        ["Latest", "14.6%"],
                        ["3yr Average", "12.5%"],
                        [" 5yr Average ", "14.2%"],
                    ],
                }
            ],
        },
    }
    ratios = [
        {"short_name": "ROE", "value": 14.6, "unit": "%"},
        {"short_name": "Net Sales", "value": 500.0, "unit": "Cr"},
        {"short_name": "Debt to Equity Ratio", "value": 0.4, "unit": ""},
        {"short_name": "Mystery", "value": 3, "unit": ""},
    ]
    dividends = [
        {"ex_date": f"202{y}-08-01", "event_details": f"Dividend of Rs.{y} per share"}
        for y in range(7)
    ]
    return "".join(
        [
            block("company_details_data", details),
            block("ratios_table", ratios),
            block("companyId", 77),
            block("company_status", "Active"),
            block("intraday_price", [[1774981800000, 1234.5]]),
            block("price_returns", {"1d": -1.0, "1y": 20.0, "3y": 999.0, "5y": 999.0}),
            block("corporate_actions", {"Dividend": dividends, "Split": []}),
            block(
                "memoryOverviewKeyEvents",
                [{"label": "Opened a plant.", "chart_date": "2026-01-02"}],
            ),
            block(
                "overview_locks",
                locks if locks is not None else {"op_metrics": {"historic": False}},
            ),
            block("plan_details", plan if plan is not None else {"plan_tier": "free"}),
            extra,
        ]
    )


def test_reads_the_facts():
    parsed = parse_company_page(page())
    assert (parsed.name, parsed.nse, parsed.status, parsed.company_id) == (
        "Acme Fine-Chem Ltd.",
        "ACMEFINE",
        "Active",
        77,
    )
    assert (parsed.price, parsed.price_date.isoformat()) == (1234.5, "2026-04-01")
    assert (parsed.market_cap_crore, parsed.pe, parsed.peg) == (1500.0, 20.5, 1.5)


def test_ratios_take_units_from_tijori_and_never_guess_money():
    units = {r.name: r.unit for r in parse_company_page(page()).ratios}
    assert units == {
        "ROE": "percent",
        "Net Sales": "crore",
        "Debt to Equity Ratio": "multiple",
        "Mystery": "as_reported",
    }


def test_tijori_opinions_are_left_out():
    dumped = parse_company_page(page()).model_dump_json()
    assert "TIJORI OPINION" not in dumped
    assert "TIJORI JUDGEMENT" not in dumped


def test_only_returns_up_to_a_year_are_kept():
    returns = parse_company_page(page()).returns_percent
    assert set(returns) == {"1d", "1m", "6m", "ytd", "1y"}
    assert 999.0 not in returns.values()


def test_dividends_are_newest_first_and_capped():
    dividends = parse_company_page(page()).dividends
    assert [d.ex_date for d in dividends] == [f"202{y}-08-01" for y in (6, 5, 4, 3, 2)]


def test_averages_are_read():
    average = parse_company_page(page()).averages[0]
    assert (average.latest, average.three_year, average.five_year, average.unit) == (
        14.6,
        12.5,
        14.2,
        "percent",
    )


@pytest.mark.parametrize(
    ("locks", "plan", "expected"),
    [
        ({"op_metrics": {"historic": False}}, {"plan_tier": "free"}, (False, False, False)),
        ({}, {}, (False, False, False)),
        (
            {
                "op_metrics": {"historic": True},
                "rev_mix": {"historic": True},
                "market_share": {"historic": True},
            },
            {"plan_tier": "premium", "ind_company": {"overview": {"rev_mix": {"historic": True}}}},
            (True, True, True),
        ),
        (
            {"op_metrics": {"historic": "yes"}, "rev_mix": {"historic": True}},
            {"plan_tier": "premium"},
            (False, False, False),
        ),
    ],
)
def test_paid_features_count_as_locked_unless_clearly_unlocked(locks, plan, expected):
    entitlements = parse_company_page(page(locks=locks, plan=plan)).entitlements
    assert (
        entitlements.metrics_history,
        entitlements.revenue_mix_history,
        entitlements.market_share_history,
    ) == expected


def test_missing_core_data_is_a_changed_site():
    with pytest.raises(ToolFailure) as caught:
        parse_company_page(block("ratios_table", []))
    assert caught.value.code is ErrorCode.UPSTREAM_CHANGED


def test_metric_list_survives_quotes_inside_onclick():
    html = (
        '<li class="indent0" metricId="11" indent="0" unit="kL" '
        'onclick="plot(\'/api/x/77/11/\', \'a\\"b\')" title="Reactor capacity">x</li>'
        '<li metricid="12" indent="1" unit="Crs" title="Sub metric">y</li>'
        '<li metricid="13">no title</li>'
    )
    assert [(m.metric_id, m.name, m.unit, m.top_level) for m in operating_metric_list(html)] == [
        ("11", "Reactor capacity", "kL", True),
        ("12", "Sub metric", "crore", False),
    ]


def test_business_mix_reads_charts_and_dated_market_shares():
    pie = "[[&quot;Widgets&quot;, 80.0], [&quot;Gadgets&quot;, 20.0]]"
    html = (
        '<div class="rmix_graph_block" company-id="1"><h4>Product Wise Break-Up </h4>'
        f'<div class="rmix_pie_chart" chart-id="9" chart-data="{pie}"></div></div>'
        '<div class="rmix_graph_block"><h4>Broken</h4>'
        '<div class="rmix_pie_chart" chart-id="8" chart-data="{bad"></div></div>'
        '<div class="market_share_card" data-title="Widgets - Market Share">'
        '<span class="value">12.5</span><span class="unit">%</span>'
        '<div class="asof">(as of May 23)</div></div>'
    )
    charts, shares = parse_business_mix(html)
    assert [(c.title, c.chart_id, [(f.name, f.value) for f in c.latest]) for c in charts] == [
        ("Product Wise Break-Up", "9", [("Widgets", 80.0), ("Gadgets", 20.0)])
    ]
    assert [(s.name, s.value, s.unit, s.as_of) for s in shares] == [
        ("Widgets", 12.5, "percent", "May 2023")
    ]
