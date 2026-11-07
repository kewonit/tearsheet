import pytest

from tearsheet.analytics.ratios import cagr_percent, growth_percent, summary


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        (110, 100, 10.0),
        (90, 100, -10.0),
        (5, None, None),
        (None, 5, None),
        (5, 0, None),
        (5, -2, None),
    ],
)
def test_growth_is_undefined_from_nothing_or_a_loss(current, previous, expected):
    assert growth_percent(current, previous) == expected


def test_cagr():
    assert cagr_percent(100, 133.1, 3) == 10.0
    assert cagr_percent(-1, 5, 3) is None
    assert cagr_percent(1, -5, 3) is None
    assert cagr_percent(1, 5, 0) is None


def test_summary_ignores_blanks():
    assert summary([3, None, 1, 2]) == {"min": 1, "median": 2, "max": 3}
    assert summary([None]) == {"min": None, "median": None, "max": None}
