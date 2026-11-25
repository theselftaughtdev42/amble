# No `from __future__ import annotations` here: FastAPI needs the real
# CurrentUser type, which is defined inside create_app().
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .settings import Settings
from .store import WalkStore
from .streak import current_streak, initials


# Tried in order for the display name; the user's sub is the last resort.
NAME_CLAIMS = ("name", "preferred_username", "email")


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

    oidc = settings.oidc
    if not oidc and not settings.dev_user:
        raise RuntimeError("Configure AMBLE_OIDC_* to sign people in (or AMBLE_DEV_USER locally)")

    # The session lives in a signed cookie: the signed-in user, plus Authlib's
    # state and nonce while a sign-in is in flight.
    app.add_middleware(
        SessionMiddleware,
        secret_key=oidc.session_secret if oidc else secrets.token_urlsafe(32),
        session_cookie="amble_session",
        max_age=30 * 24 * 3600,
        same_site="lax",
        https_only=(settings.public_url or "").startswith("https://"),
    )

    if oidc:
        oauth = OAuth()
        provider = oauth.register(
            "oidc",
            server_metadata_url=oidc.metadata_url,
            client_id=oidc.client_id,
            client_secret=oidc.client_secret,
            client_kwargs={
                "scope": oidc.scope,
                "code_challenge_method": "S256",
                **({"token_endpoint_auth_method": oidc.token_auth_method}
                   if oidc.token_auth_method else {}),
            },
        )
        app.state.oidc = provider

        def absolute_url(request: Request, path: str) -> str:
            # Behind a TLS-terminating proxy the request may look like plain
            # http, so prefer AMBLE_PUBLIC_URL when it's set.
            return (settings.public_url or str(request.base_url).rstrip("/")) + path

        async def fetch_userinfo(token: dict, sub: str) -> dict:
            metadata = await provider.load_server_metadata()
            if not metadata.get("userinfo_endpoint"):
                return {}
            try:
                info = await provider.userinfo(token=token)
            except Exception:  # best effort: the name only feeds the badge
                return {}
            # The spec requires a matching sub; ignore the response otherwise.
            return dict(info) if info.get("sub") == sub else {}

        @app.get("/auth/login", include_in_schema=False)
        async def login(request: Request):
            return await provider.authorize_redirect(
                request, absolute_url(request, "/auth/callback")
            )

        @app.get("/auth/callback", include_in_schema=False)
        async def callback(request: Request) -> RedirectResponse:
            try:
                token = await provider.authorize_access_token(request)
            except OAuthError as err:
                raise HTTPException(status_code=400, detail=f"Sign-in failed: {err.error}")
            # ID token claims, already verified by Authlib.
            claims = dict(token.get("userinfo") or {})
            sub = claims.get("sub")
            if not sub:
                raise HTTPException(status_code=400, detail="Sign-in failed: no subject")
            if not any(claims.get(c) for c in NAME_CLAIMS):
                # Some providers keep profile claims out of the ID token.
                claims |= await fetch_userinfo(token, sub)
            # sub is the one claim OIDC guarantees to be stable and unique.
            request.session["user"] = {
                "username": sub,
                "name": next((claims[c] for c in NAME_CLAIMS if claims.get(c)), sub),
            }
            request.session["id_token"] = token.get("id_token")
            return RedirectResponse("/", status_code=303)

        @app.get("/auth/logout", include_in_schema=False)
        async def logout(request: Request):
            id_token = request.session.get("id_token")
            request.session.clear()
            metadata = await provider.load_server_metadata()
            if metadata.get("end_session_endpoint"):
                # Sign out at the provider too, then come back to Amble.
                return await provider.logout_redirect(
                    request,
                    post_logout_redirect_uri=absolute_url(request, "/"),
                    id_token_hint=id_token,
                )
            return RedirectResponse("/", status_code=303)

    def current_user(request: Request) -> User:
        if user := request.session.get("user"):
            return User(user["username"], user["name"])
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
