"""Read page text from PDF filings, within limits."""

from pathlib import Path

from pypdf import PdfReader

from tearsheet.core.errors import ErrorCode, TearsheetError

MAX_PAGES_SCANNED = 400
MAX_PAGES_RETURNED = 10
MAX_CHARS_PER_PAGE = 6000


def _reader(path: Path) -> PdfReader:
    try:
        return PdfReader(path)
    except Exception as exc:  # pypdf raises many types for damaged files
        raise TearsheetError(ErrorCode.INVALID_INPUT, f"{path.name} isn't a readable PDF.") from exc


def page_count(path: Path) -> int:
    return len(_reader(path).pages)


def page_texts(path: Path, first: int, last: int) -> list[tuple[int, str]]:
    """Text of pages first to last, numbered from 1, capped in count and length."""
    reader = _reader(path)
    last = min(last, len(reader.pages), first + MAX_PAGES_RETURNED - 1)
    pages = []
    for number in range(first, last + 1):
        try:
            text = reader.pages[number - 1].extract_text() or ""
        except Exception:  # one bad page shouldn't hide the rest
            text = ""
        pages.append((number, " ".join(text.split())[:MAX_CHARS_PER_PAGE]))
    return pages


def search_pdf(path: Path, query: str, limit: int) -> list[tuple[int, str]]:
    """Pages containing the query, with a short snippet around the first hit."""
    reader = _reader(path)
    wanted = query.lower()
    hits = []
    for index, page in enumerate(reader.pages[:MAX_PAGES_SCANNED]):
        try:
            text = " ".join((page.extract_text() or "").split())
        except Exception:
            continue
        at = text.lower().find(wanted)
        if at >= 0:
            hits.append((index + 1, text[max(0, at - 120) : at + len(query) + 180]))
            if len(hits) >= limit:
                break
    return hits
