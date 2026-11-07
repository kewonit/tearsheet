"""Where tearsheet keeps its files. All of them sit outside the repository."""

import os
from pathlib import Path


def home_dir() -> Path:
    """Return tearsheet's private folder, creating it owner-only if needed."""
    override = os.environ.get("TEARSHEET_HOME")
    path = Path(override).expanduser() if override else Path.home() / ".tearsheet"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def session_path() -> Path:
    return home_dir() / "session.json"


def cache_path() -> Path:
    return home_dir() / "cache.sqlite3"


def filings_dir() -> Path:
    """Return the folder of filings the user downloaded. It may not exist yet."""
    override = os.environ.get("TEARSHEET_FILINGS_DIR")
    return Path(override).expanduser() if override else home_dir() / "filings"
