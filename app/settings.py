from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """Runtime configuration, read from AMBLE_* environment variables."""

    db_path: Path = ROOT / "data" / "amble.db"
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/London"))
    # Display name used when no authentik headers arrive. Only set this for
    # local development: in production every request comes through authentik.
    dev_user: str | None = None
    frontend_dir: Path = ROOT / "frontend"

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        return cls(
            db_path=Path(os.environ.get("AMBLE_DB", defaults.db_path)),
            tz=ZoneInfo(os.environ.get("AMBLE_TZ", "Europe/London")),
            dev_user=os.environ.get("AMBLE_DEV_USER") or None,
        )
