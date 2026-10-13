from __future__ import annotations

from collections.abc import Collection
from datetime import date, timedelta


def current_streak(walked: Collection[date], today: date) -> int:
    """Consecutive walked days up to today.

    A streak stays alive until midnight: if today hasn't been walked yet,
    count back from yesterday instead.
    """
    day = today if today in walked else today - timedelta(days=1)
    streak = 0
    while day in walked:
        streak += 1
        day -= timedelta(days=1)
    return streak


def initials(name: str) -> str:
    """First letter of the first and last words: 'Jane Q Doe' -> 'JD'."""
    words = name.split()
    if not words:
        return "?"
    first = words[0][0]
    last = words[-1][0] if len(words) > 1 else ""
    return (first + last).upper()
