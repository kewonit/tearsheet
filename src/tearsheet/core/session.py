"""Store and inspect the user's Tijori session.

The session file holds live login cookies. Nothing here returns or logs a
cookie's value: SessionInfo only reports whether a session exists and when it
ends.
"""

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

TIJORI_DOMAIN = "tijorifinance.com"
SESSION_COOKIE = "sessionid"


class SessionState(StrEnum):
    NONE = "none"
    SAVED = "saved"
    EXPIRED = "expired"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class SessionInfo:
    state: SessionState
    saved_at: datetime | None = None
    expires_at: datetime | None = None
    loose_permissions: bool = False


def write_session(storage_state: dict[str, Any], path: Path) -> None:
    """Save a Playwright storage state, owner-only and all at once.

    Writing to a temporary file first means a crash can't leave a half-written
    session, and mkstemp creates that file owner-only.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".session-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(storage_state, file)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _session_cookie(storage_state: dict[str, Any]) -> dict[str, Any] | None:
    for cookie in storage_state.get("cookies", []):
        domain = cookie.get("domain", "").lstrip(".")
        is_tijori = domain == TIJORI_DOMAIN or domain.endswith("." + TIJORI_DOMAIN)
        if cookie.get("name") == SESSION_COOKIE and is_tijori:
            return cookie
    return None


def read_session_info(path: Path, *, now: datetime | None = None) -> SessionInfo:
    """Describe the saved session without contacting Tijori.

    SAVED means a cookie exists and hasn't passed its expiry date. Tijori may
    still have ended the session on its side.
    """
    try:
        file_stat = path.stat()
    except FileNotFoundError:
        return SessionInfo(SessionState.NONE)

    saved_at = datetime.fromtimestamp(file_stat.st_mtime, UTC)
    loose = bool(stat.S_IMODE(file_stat.st_mode) & 0o077)
    try:
        storage_state = json.loads(path.read_text())
        cookie = _session_cookie(storage_state)
    except (OSError, ValueError, AttributeError, TypeError):
        return SessionInfo(SessionState.UNREADABLE, saved_at, None, loose)
    if cookie is None:
        return SessionInfo(SessionState.UNREADABLE, saved_at, None, loose)

    # Playwright uses -1 for a cookie that lasts until the browser closes.
    expires = cookie.get("expires", -1)
    if not isinstance(expires, int | float) or expires <= 0:
        return SessionInfo(SessionState.SAVED, saved_at, None, loose)
    expires_at = datetime.fromtimestamp(expires, UTC)
    expired = (now or datetime.now(UTC)) >= expires_at
    state = SessionState.EXPIRED if expired else SessionState.SAVED
    return SessionInfo(state, saved_at, expires_at, loose)
