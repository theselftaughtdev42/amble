from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path


class WalkStore:
    """One row per user per day they walked."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS walks (
                    user      TEXT NOT NULL,
                    day       TEXT NOT NULL,
                    logged_at TEXT NOT NULL,
                    PRIMARY KEY (user, day)
                )
                """
            )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def log(self, user: str, day: date, logged_at: datetime) -> None:
        """Record a walk. Logging the same day twice keeps the first time."""
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO walks (user, day, logged_at) VALUES (?, ?, ?)",
                (user, day.isoformat(), logged_at.isoformat()),
            )

    def undo(self, user: str, day: date) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM walks WHERE user = ? AND day = ?",
                (user, day.isoformat()),
            )

    def logged_at(self, user: str, day: date) -> datetime | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT logged_at FROM walks WHERE user = ? AND day = ?",
                (user, day.isoformat()),
            ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def days(self, user: str) -> set[date]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT day FROM walks WHERE user = ?", (user,)
            ).fetchall()
        return {date.fromisoformat(r[0]) for r in rows}
