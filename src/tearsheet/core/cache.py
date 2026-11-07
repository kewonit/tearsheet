"""A local cache that survives restarts.

The cache belongs to one user on one machine. It is never shared, because the
data in it may only be stored for that user's personal use. See
docs/DATA-USE.md.
"""

import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    dataset    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    PRIMARY KEY (dataset, key)
)
"""


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    fetched_at: float
    stale: bool


class Cache:
    """Store JSON values by dataset and key, with an expiry for each."""

    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        # Create the file first so it is owner-only from the start.
        os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=5)
        with self._lock, self._db:
            self._db.execute(_SCHEMA)

    def get(self, dataset: str, key: str, *, allow_stale: bool = False) -> CacheEntry | None:
        """Return an entry, or None if it is missing or expired.

        With allow_stale, an expired entry comes back marked stale, so a tool
        can still answer when the source is down and say the data is old.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT value, fetched_at, expires_at FROM entries WHERE dataset = ? AND key = ?",
                (dataset, key),
            ).fetchone()
        if row is None:
            return None
        value, fetched_at, expires_at = row
        stale = self._clock() >= expires_at
        if stale and not allow_stale:
            return None
        return CacheEntry(json.loads(value), fetched_at, stale)

    def put(self, dataset: str, key: str, value: Any, *, ttl_s: float) -> None:
        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        now = self._clock()
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?, ?)",
                (dataset, key, json.dumps(value, ensure_ascii=False), now, now + ttl_s),
            )

    def counts(self) -> dict[str, int]:
        """Return how many entries each dataset holds, fresh or stale."""
        with self._lock:
            rows = self._db.execute(
                "SELECT dataset, COUNT(*) FROM entries GROUP BY dataset ORDER BY dataset"
            ).fetchall()
        return dict(rows)

    def purge_expired(self) -> int:
        """Delete expired entries and return how many went."""
        with self._lock, self._db:
            cursor = self._db.execute("DELETE FROM entries WHERE expires_at <= ?", (self._clock(),))
        return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()
