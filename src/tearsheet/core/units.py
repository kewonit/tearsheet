"""Convert money figures to one scale.

Sources report in rupees, lakh, million or crore. Misreading the scale is an
easy and damaging mistake, so every figure tearsheet returns is in crore and
says so.
"""

from decimal import Decimal, InvalidOperation
from enum import StrEnum


class Scale(StrEnum):
    RUPEES = "rupees"
    THOUSAND = "thousand"
    LAKH = "lakh"
    MILLION = "million"
    CRORE = "crore"
    BILLION = "billion"


_RUPEES_PER_UNIT = {
    Scale.RUPEES: Decimal(1),
    Scale.THOUSAND: Decimal(10) ** 3,
    Scale.LAKH: Decimal(10) ** 5,
    Scale.MILLION: Decimal(10) ** 6,
    Scale.CRORE: Decimal(10) ** 7,
    Scale.BILLION: Decimal(10) ** 9,
}


def to_crore(value: Decimal | int | float | str, scale: Scale) -> Decimal:
    """Return value, given in scale, as a number of crore.

    Raises ValueError for anything that isn't a finite number. Floats go
    through str() so 0.1 stays 0.1 rather than its binary approximation.
    """
    if isinstance(value, bool):
        raise ValueError("expected a number, got a bool")
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    return amount * _RUPEES_PER_UNIT[scale] / _RUPEES_PER_UNIT[Scale.CRORE]
