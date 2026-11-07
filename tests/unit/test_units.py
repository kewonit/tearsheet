from decimal import Decimal

import pytest

from tearsheet.core.units import Scale, to_crore


@pytest.mark.parametrize(
    ("value", "scale", "expected"),
    [
        (1, Scale.CRORE, "1"),
        (10_000_000, Scale.RUPEES, "1"),
        (100, Scale.LAKH, "1"),
        (10, Scale.MILLION, "1"),
        (1, Scale.BILLION, "100"),
        (10_000, Scale.THOUSAND, "1"),
        (-250, Scale.LAKH, "-2.5"),
        (0, Scale.MILLION, "0"),
    ],
)
def test_converts_to_crore(value, scale, expected):
    assert to_crore(value, scale) == Decimal(expected)


def test_floats_keep_their_written_value():
    assert to_crore(0.1, Scale.CRORE) == Decimal("0.1")


def test_accepts_numeric_strings():
    assert to_crore(" 1234.5 ", Scale.CRORE) == Decimal("1234.5")


@pytest.mark.parametrize("bad", ["", "n/a", "12,000", None, True, "NaN", "Infinity", float("nan")])
def test_rejects_anything_that_is_not_a_finite_number(bad):
    with pytest.raises(ValueError):
        to_crore(bad, Scale.CRORE)
