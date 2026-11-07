"""Find which local filings belong to a company, without contacting anyone."""

import re
from datetime import date
from pathlib import Path

from tearsheet.core.errors import TearsheetError
from tearsheet.sources.filings.files import PDF_SUFFIXES, XBRL_SUFFIXES, list_filings
from tearsheet.sources.filings.xbrl import XbrlFiling, read_xbrl

_PARSED: dict[tuple[str, float, int], XbrlFiling | None] = {}


def parsed_xbrl(path: Path) -> XbrlFiling | None:
    """Parse once per file version. Unreadable files are skipped, not fatal."""
    stat = path.stat()
    key = (str(path), stat.st_mtime, stat.st_size)
    if key not in _PARSED:
        try:
            _PARSED[key] = read_xbrl(path)
        except TearsheetError:
            _PARSED[key] = None
    return _PARSED[key]


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^A-Za-z0-9]+", text.upper()) if t}


def pdf_owner_tokens(folder: Path, path: Path) -> set[str]:
    """PDFs are matched to a company by their folder name, or failing that their file name."""
    parts = path.relative_to(folder.resolve()).parts
    return _tokens(parts[0]) if len(parts) > 1 else _tokens(path.stem)


def belongs_to(folder: Path, path: Path, company: str, *identifiers: str | None) -> bool:
    wanted = {i.upper() for i in (company, *identifiers) if i}
    if path.suffix.lower() in XBRL_SUFFIXES:
        filing = parsed_xbrl(path)
        if filing is None:
            return False
        names = {filing.symbol, filing.scrip_code}
        if wanted & {n.upper() for n in names if n}:
            return True
        return bool(filing.name and company and company.lower() in filing.name.lower())
    if path.suffix.lower() in PDF_SUFFIXES:
        tokens = pdf_owner_tokens(folder, path)
        return bool(wanted & tokens) or (company.upper() in tokens if company else False)
    return False


def xbrl_for_quarter(
    folder: Path, nse: str | None, bse: str | None, basis: str, end: date
) -> list[tuple[Path, XbrlFiling]]:
    found = []
    for path in list_filings(folder):
        if path.suffix.lower() not in XBRL_SUFFIXES:
            continue
        filing = parsed_xbrl(path)
        if filing is None:
            continue
        ours = (nse and filing.symbol == nse.upper()) or (bse and filing.scrip_code == bse)
        if (
            ours
            and (filing.basis or "").startswith(basis[:4])
            and any(c.end == end for c in filing.contexts.values())
        ):
            found.append((path, filing))
    return found
