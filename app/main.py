# No `from __future__ import annotations` here: FastAPI needs the real
# CurrentUser type, which is defined inside create_app().
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .settings import Settings
from .store import WalkStore
from .streak import current_streak, initials


@dataclass(frozen=True)
class User:
    username: str
    name: str


class Me(BaseModel):
    name: str
    initials: str


class Today(BaseModel):
    date: date
    walked: bool
    logged_time: str | None  # "HH:MM" in the app's time zone
    streak: int
    seconds_left: int  # until midnight in the app's time zone


def create_app(
    settings: Settings | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    store = WalkStore(settings.db_path)
    tz = settings.tz

    def now() -> datetime:
        return (clock() if clock else datetime.now(UTC)).astimezone(tz)

    app = FastAPI(title="Amble", docs_url=None, redoc_url=None, openapi_url=None)

    def current_user(
        x_authentik_username: Annotated[str | None, Header()] = None,
        x_authentik_name: Annotated[str | None, Header()] = None,
    ) -> User:
        # authentik's proxy outpost adds these headers to every request it
        # lets through. Only expose the app via the proxy, or they can be faked.
        if x_authentik_username:
            return User(x_authentik_username, x_authentik_name or x_authentik_username)
        if settings.dev_user:
            return User("dev", settings.dev_user)
        raise HTTPException(status_code=401, detail="Not signed in")

    CurrentUser = Annotated[User, Depends(current_user)]

    def today_status(user: User) -> Today:
        current = now()
        today = current.date()
        logged = store.logged_at(user.username, today)
        midnight = datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)
        # Subtract in UTC so the clock-change days come out right.
        left = midnight.astimezone(UTC) - current.astimezone(UTC)
        return Today(
            date=today,
            walked=logged is not None,
            logged_time=logged.astimezone(tz).strftime("%H:%M") if logged else None,
            streak=current_streak(store.days(user.username), today),
            seconds_left=max(0, int(left.total_seconds())),
        )

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/me")
    def me(user: CurrentUser) -> Me:
        return Me(name=user.name, initials=initials(user.name))

    @app.get("/api/today")
    def get_today(user: CurrentUser) -> Today:
        return today_status(user)

    @app.post("/api/walks")
    def log_walk(user: CurrentUser) -> Today:
        current = now()
        store.log(user.username, current.date(), current)
        return today_status(user)

    @app.delete("/api/walks/today")
    def undo_walk(user: CurrentUser) -> Today:
        store.undo(user.username, now().date())
        return today_status(user)

    # Static frontend. API routes above always win over these files.
    app.frontend("/", directory=settings.frontend_dir, fallback=None)

    return app
