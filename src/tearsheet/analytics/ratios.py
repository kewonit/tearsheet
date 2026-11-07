"""Calculations done on the server, so the model never does the arithmetic."""

from statistics import median


def growth_percent(current: float | None, previous: float | None) -> float | None:
    """Percentage change. Undefined when the earlier figure is missing, zero or negative."""
    if current is None or previous is None or previous <= 0:
        return None
    return round((current / previous - 1) * 100, 2)


def cagr_percent(first: float | None, last: float | None, years: int) -> float | None:
    """Compound annual growth. Undefined across a sign change or a zero start."""
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return round(((last / first) ** (1 / years) - 1) * 100, 2)


def summary(values: list[float | None]) -> dict[str, float | None]:
    """Minimum, median and maximum of the figures that exist."""
    present = [value for value in values if value is not None]
    if not present:
        return {"min": None, "median": None, "max": None}
    return {"min": min(present), "median": round(median(present), 4), "max": max(present)}
