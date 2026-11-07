"""Safe access to the user's filings folder.

Filings are files the user downloaded by hand. Tearsheet never fetches them,
because the exchanges prohibit automated collection. Only files inside the
folder can be read, whatever path an agent asks for.
"""

from pathlib import Path

from tearsheet.core.errors import ErrorCode, TearsheetError

XBRL_SUFFIXES = {".xml", ".xbrl"}
PDF_SUFFIXES = {".pdf"}
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_FILES = 2000


def list_filings(folder: Path) -> list[Path]:
    """Every readable filing in the folder, as paths inside it, newest first."""
    if not folder.is_dir():
        return []
    root = folder.resolve()
    found = []
    for path in folder.rglob("*"):
        if path.suffix.lower() not in XBRL_SUFFIXES | PDF_SUFFIXES or not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_relative_to(root) and resolved.stat().st_size <= MAX_FILE_BYTES:
            found.append(resolved)
        if len(found) >= MAX_FILES:
            break
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def resolve_filing(folder: Path, name: str) -> Path:
    """Turn a name an agent gives back into a file, refusing anything outside the folder."""
    if not name or Path(name).is_absolute():
        raise TearsheetError(ErrorCode.INVALID_INPUT, "Give a filing name from search_filings.")
    root = folder.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise TearsheetError(ErrorCode.INVALID_INPUT, "That path is outside the filings folder.")
    if not path.is_file():
        raise TearsheetError(ErrorCode.NOT_FOUND, f"No filing called {name!r}.")
    if path.suffix.lower() not in XBRL_SUFFIXES | PDF_SUFFIXES:
        raise TearsheetError(ErrorCode.INVALID_INPUT, "Only XBRL and PDF filings can be read.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise TearsheetError(ErrorCode.INVALID_INPUT, "That filing is too large to read.")
    return path


def display_name(folder: Path, path: Path) -> str:
    return path.relative_to(folder.resolve()).as_posix()
