from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import OIDCSettings, Settings
from app.streak import current_streak, initials

OIDC = OIDCSettings(
    issuer="https://auth.example.com/application/o/amble/",
    client_id="amble",
    client_secret="client-secret",
    session_secret="session-secret",
)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    # 23:14 BST on Tue 13 Oct 2026
    return Clock(datetime(2026, 10, 13, 22, 14, tzinfo=UTC))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "amble.db", oidc=OIDC)


@pytest.fixture
def app(settings: Settings, clock: Clock) -> FastAPI:
    app = create_app(settings, clock=clock)

    # Stand in for the provider: the "code" in the callback is the userinfo.
    async def authorize_access_token(request: Request) -> dict:
        username, _, name = request.query_params["code"].partition(":")
        claims = {"sub": f"sub-{username}", "name": name}
        return {"id_token": "id-token", "userinfo": claims}

    async def load_server_metadata() -> dict:
        return {}

    app.state.oidc.authorize_access_token = authorize_access_token
    app.state.oidc.load_server_metadata = load_server_metadata
    return app


def sign_in(app: FastAPI, username: str, name: str) -> TestClient:
    client = TestClient(app)
    res = client.get("/auth/callback", params={"code": f"{username}:{name}"}, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/"
    return client


@pytest.fixture
def anon(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return sign_in(app, "jane", "Jane Q Doe")


def test_requires_sign_in(anon: TestClient) -> None:
    assert anon.get("/api/today").status_code == 401


def test_ignores_proxy_auth_headers(anon: TestClient) -> None:
    headers = {"X-authentik-username": "jane", "X-Forwarded-User": "jane"}
    assert anon.get("/api/today", headers=headers).status_code == 401


def test_login_redirects_to_provider(anon: TestClient, app: FastAPI) -> None:
    async def load_server_metadata() -> dict:
        return {"authorization_endpoint": "https://auth.example.com/authorize"}

    app.state.oidc.load_server_metadata = load_server_metadata
    res = anon.get("/auth/login", follow_redirects=False)
    assert res.status_code == 302
    location = res.headers["location"]
    assert location.startswith("https://auth.example.com/authorize?")
    assert "client_id=amble" in location
    assert "redirect_uri=http%3A%2F%2Ftestserver%2Fauth%2Fcallback" in location
    assert "code_challenge_method=S256" in location


def test_callback_rejects_provider_error(anon: TestClient, app: FastAPI) -> None:
    del app.state.oidc.authorize_access_token  # back to Authlib's own
    res = anon.get("/auth/callback", params={"error": "access_denied"})
    assert res.status_code == 400


def claims_sign_in(app: FastAPI, claims: dict, userinfo: dict | None = None) -> TestClient:
    """Sign in with the given ID token claims and userinfo endpoint response."""

    async def authorize_access_token(request: Request) -> dict:
        return {"access_token": "at", "userinfo": claims}

    async def load_server_metadata() -> dict:
        return {"userinfo_endpoint": "https://auth.example.com/userinfo"} if userinfo else {}

    async def fetch_userinfo(**kwargs) -> dict:
        return userinfo

    app.state.oidc.authorize_access_token = authorize_access_token
    app.state.oidc.load_server_metadata = load_server_metadata
    app.state.oidc.userinfo = fetch_userinfo
    client = TestClient(app)
    assert client.get("/auth/callback", follow_redirects=False).status_code == 303
    return client


def test_walks_are_keyed_by_sub(app: FastAPI) -> None:
    # Same username, different subjects: two different people.
    one = claims_sign_in(app, {"sub": "1", "preferred_username": "jane"})
    one.post("/api/walks")
    two = claims_sign_in(app, {"sub": "2", "preferred_username": "jane"})
    assert two.get("/api/today").json()["walked"] is False


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"name": "Jane Doe", "preferred_username": "jd", "email": "j@x"}, "Jane Doe"),
        ({"preferred_username": "jd", "email": "j@x"}, "jd"),
        ({"email": "j@x"}, "j@x"),
        ({}, "abc123"),
    ],
)
def test_display_name_fallbacks(app: FastAPI, claims: dict, expected: str) -> None:
    client = claims_sign_in(app, {"sub": "abc123", **claims})
    assert client.get("/api/me").json()["name"] == expected


def test_name_from_userinfo_endpoint(app: FastAPI) -> None:
    client = claims_sign_in(app, {"sub": "abc"}, userinfo={"sub": "abc", "name": "Sam Lee"})
    assert client.get("/api/me").json() == {"name": "Sam Lee", "initials": "SL"}


def test_userinfo_with_other_sub_is_ignored(app: FastAPI) -> None:
    client = claims_sign_in(app, {"sub": "abc"}, userinfo={"sub": "evil", "name": "Mallory"})
    assert client.get("/api/me").json()["name"] == "abc"


def test_callback_needs_sub(app: FastAPI) -> None:
    async def authorize_access_token(request: Request) -> dict:
        return {"userinfo": {"name": "No Sub"}}

    app.state.oidc.authorize_access_token = authorize_access_token
    assert TestClient(app).get("/auth/callback").status_code == 400


@pytest.mark.parametrize("method", [None, "client_secret_basic", "client_secret_post"])
def test_token_auth_method(tmp_path: Path, method: str | None) -> None:
    oidc = OIDCSettings(**{**OIDC.__dict__, "token_auth_method": method})
    app = create_app(Settings(db_path=tmp_path / "amble.db", oidc=oidc))
    kwargs = app.state.oidc.client_kwargs
    assert kwargs.get("token_endpoint_auth_method") == method


def test_rejects_unknown_token_auth_method(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "AMBLE_OIDC_ISSUER": "https://auth.example.com/",
        "AMBLE_OIDC_CLIENT_ID": "a",
        "AMBLE_OIDC_CLIENT_SECRET": "b",
        "AMBLE_SESSION_SECRET": "c",
        "AMBLE_OIDC_TOKEN_AUTH_METHOD": "private_key_jwt",
    }.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match="TOKEN_AUTH_METHOD"):
        Settings.from_env()


def test_logout_clears_session(client: TestClient) -> None:
    res = client.get("/auth/logout", follow_redirects=False)
    assert res.status_code == 303
    assert client.get("/api/me").status_code == 401


def test_logout_signs_out_at_provider(client: TestClient, app: FastAPI) -> None:
    async def load_server_metadata() -> dict:
        return {"end_session_endpoint": "https://auth.example.com/end-session"}

    app.state.oidc.load_server_metadata = load_server_metadata
    res = client.get("/auth/logout", follow_redirects=False)
    assert res.status_code == 302
    location = res.headers["location"]
    assert location.startswith("https://auth.example.com/end-session?")
    assert "id_token_hint=id-token" in location
    assert client.get("/api/me").status_code == 401


def test_needs_a_way_to_sign_in(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        create_app(Settings(db_path=tmp_path / "amble.db"))


def test_dev_user_fallback(tmp_path: Path, clock: Clock) -> None:
    settings = Settings(db_path=tmp_path / "amble.db", dev_user="Dev Person")
    res = TestClient(create_app(settings, clock=clock)).get("/api/me")
    assert res.json() == {"name": "Dev Person", "initials": "DP"}


def test_me_uses_first_and_last_initials(client: TestClient) -> None:
    assert client.get("/api/me").json() == {
        "name": "Jane Q Doe",
        "initials": "JD",
    }


def test_today_before_walking(client: TestClient) -> None:
    body = client.get("/api/today").json()
    assert body == {
        "date": "2026-10-13",
        "walked": False,
        "logged_time": None,
        "streak": 0,
        "seconds_left": 46 * 60,
    }


def test_log_walk_and_undo(client: TestClient) -> None:
    body = client.post("/api/walks").json()
    assert body["walked"] is True
    assert body["logged_time"] == "23:14"
    assert body["streak"] == 1

    # Logging twice in a day is harmless.
    assert client.post("/api/walks").json()["streak"] == 1

    body = client.delete("/api/walks/today").json()
    assert body["walked"] is False
    assert body["streak"] == 0


def test_streak_survives_until_midnight(client: TestClient, clock: Clock) -> None:
    for days_ago in (3, 2, 1):
        clock.now = datetime(2026, 10, 13, 9, tzinfo=UTC) - timedelta(days=days_ago)
        client.post("/api/walks")

    clock.now = datetime(2026, 10, 13, 22, 14, tzinfo=UTC)
    body = client.get("/api/today").json()
    assert body["walked"] is False
    assert body["streak"] == 3

    assert client.post("/api/walks").json()["streak"] == 4


def test_missing_a_day_resets_streak(client: TestClient, clock: Clock) -> None:
    clock.now = datetime(2026, 10, 11, 9, tzinfo=UTC)
    client.post("/api/walks")
    clock.now = datetime(2026, 10, 13, 9, tzinfo=UTC)
    assert client.get("/api/today").json()["streak"] == 0


def test_users_are_separate(client: TestClient, app: FastAPI) -> None:
    client.post("/api/walks")
    other = sign_in(app, "sam", "Sam")
    assert other.get("/api/today").json()["walked"] is False


def test_day_boundary_uses_local_time(client: TestClient, clock: Clock) -> None:
    # 23:30 UTC on the 13th is already 00:30 on the 14th in London (BST).
    clock.now = datetime(2026, 10, 13, 23, 30, tzinfo=UTC)
    assert client.get("/api/today").json()["date"] == "2026-10-14"


def test_countdown_on_clock_change_day(client: TestClient, clock: Clock) -> None:
    # 00:30 BST on Sun 25 Oct; clocks go back an hour that night, so the day
    # has 25 hours and 24.5 of them are left.
    clock.now = datetime(2026, 10, 24, 23, 30, tzinfo=UTC)
    body = client.get("/api/today").json()
    assert body["date"] == "2026-10-25"
    assert body["seconds_left"] == int(24.5 * 3600)


def test_serves_frontend(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "Amble" in res.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/api/nope").status_code == 404


def test_serves_pwa_files(client: TestClient) -> None:
    manifest = client.get("/manifest.webmanifest")
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    for icon in manifest.json()["icons"]:
        assert client.get(icon["src"]).status_code == 200
    sw = client.get("/sw.js")
    assert "javascript" in sw.headers["content-type"]


def test_streak_helper() -> None:
    today = date(2026, 10, 13)
    walked = {today - timedelta(days=n) for n in (0, 1, 2, 4)}
    assert current_streak(walked, today) == 3
    assert current_streak(set(), today) == 0


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Jane Q Doe", "JD"), ("cher", "C"), ("  ", "?"), ("Ana  Maria Lopez", "AL")],
)
def test_initials(name: str, expected: str) -> None:
    assert initials(name) == expected
