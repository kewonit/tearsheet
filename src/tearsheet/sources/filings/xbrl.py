"""A small reader for the XBRL results filings Indian companies submit.

Experimental: tested only on synthetic filings. Elements are matched by local
name, so taxonomy versions don't matter, and money is reported in rupees, so
it's converted to crore. Parsing uses defusedxml, which refuses the entity
tricks that can make XML parsers misbehave.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from defusedxml import ElementTree
from pydantic import BaseModel

from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.core.units import Scale, to_crore

XBRLI = "{http://www.xbrl.org/2003/instance}"
_META = {
    "symbol": ("Symbol", "NSESymbol"),
    "scrip_code": ("ScripCode", "BSEScripCode"),
    "name": ("NameOfTheCompany", "NameOfCompany"),
    "basis": ("NatureOfReportStandaloneConsolidated",),
    "period_start": ("DateOfStartOfReportingPeriod",),
    "period_end": ("DateOfEndOfReportingPeriod",),
}
QUARTER_DAYS = range(85, 96)


class Context(BaseModel):
    start: date | None
    end: date
    has_dimensions: bool


class Fact(BaseModel):
    concept: str
    value: str
    context: str
    unit: str | None


class XbrlFiling(BaseModel):
    symbol: str | None
    scrip_code: str | None
    name: str | None
    basis: str | None
    period_start: date | None
    period_end: date | None
    contexts: dict[str, Context]
    facts: list[Fact]

    def amount_crore(
        self, concepts: tuple[str, ...], end: date, quarter: bool
    ) -> tuple[float, str] | None:
        """The first matching rupee amount for a period ending on end, as crore.

        Only contexts without dimensions count, because dimensioned ones are
        breakdowns rather than the company total. A results filing for a
        second quarter also holds half-year figures, so quarter picks the
        context lasting about three months.
        """
        for concept in concepts:
            for fact in self.facts:
                if fact.concept != concept:
                    continue
                context = self.contexts.get(fact.context)
                if context is None or context.has_dimensions or context.end != end:
                    continue
                if quarter and (
                    context.start is None or (end - context.start).days not in QUARTER_DAYS
                ):
                    continue
                try:
                    amount = to_crore(Decimal(fact.value), Scale.RUPEES)
                except (InvalidOperation, ValueError):
                    continue
                return round(float(amount), 4), concept
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _date(text: str | None) -> date | None:
    try:
        return date.fromisoformat((text or "").strip()[:10])
    except ValueError:
        return None


def read_xbrl(path: Path) -> XbrlFiling:
    try:
        root = ElementTree.parse(path).getroot()
    except Exception as exc:  # defusedxml raises several types for unsafe or broken files
        raise TearsheetError(
            ErrorCode.INVALID_INPUT, f"{path.name} isn't a readable XBRL file."
        ) from exc
    contexts = {}
    for element in root.iter(f"{XBRLI}context"):
        period = element.find(f"{XBRLI}period")
        if period is None:
            continue
        end = _date(period.findtext(f"{XBRLI}endDate") or period.findtext(f"{XBRLI}instant"))
        if end is None:
            continue
        contexts[element.get("id", "")] = Context(
            start=_date(period.findtext(f"{XBRLI}startDate")),
            end=end,
            has_dimensions=element.find(f".//{XBRLI}segment") is not None
            or element.find(f".//{XBRLI}scenario") is not None,
        )
    facts = [
        Fact(
            concept=_local(element.tag),
            value=(element.text or "").strip(),
            context=element.get("contextRef", ""),
            unit=element.get("unitRef"),
        )
        for element in root
        if element.get("contextRef") and (element.text or "").strip()
    ]
    meta = {}
    for key, names in _META.items():
        meta[key] = next((f.value for name in names for f in facts if f.concept == name), None)
    return XbrlFiling(
        symbol=(meta["symbol"] or "").upper() or None,
        scrip_code=meta["scrip_code"],
        name=meta["name"],
        basis=(meta["basis"] or "").lower() or None,
        period_start=_date(meta["period_start"]),
        period_end=_date(meta["period_end"]),
        contexts=contexts,
        facts=facts,
    )
