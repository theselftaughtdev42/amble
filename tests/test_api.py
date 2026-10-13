from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.streak import current_streak, initials

HEADERS = {"X-authentik-username": "jane", "X-authentik-name": "Jane Q Doe"}


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
    return Settings(db_path=tmp_path / "amble.db")


@pytest.fixture
def client(settings: Settings, clock: Clock) -> TestClient:
    return TestClient(create_app(settings, clock=clock))


def test_requires_authentik_headers(client: TestClient) -> None:
    assert client.get("/api/today").status_code == 401


def test_dev_user_fallback(tmp_path: Path, clock: Clock) -> None:
    settings = Settings(db_path=tmp_path / "amble.db", dev_user="Dev Person")
    res = TestClient(create_app(settings, clock=clock)).get("/api/me")
    assert res.json() == {"name": "Dev Person", "initials": "DP"}


def test_me_uses_first_and_last_initials(client: TestClient) -> None:
    assert client.get("/api/me", headers=HEADERS).json() == {
        "name": "Jane Q Doe",
        "initials": "JD",
    }


def test_today_before_walking(client: TestClient) -> None:
    body = client.get("/api/today", headers=HEADERS).json()
    assert body == {
        "date": "2026-10-13",
        "walked": False,
        "logged_time": None,
        "streak": 0,
        "seconds_left": 46 * 60,
    }


def test_log_walk_and_undo(client: TestClient) -> None:
    body = client.post("/api/walks", headers=HEADERS).json()
    assert body["walked"] is True
    assert body["logged_time"] == "23:14"
    assert body["streak"] == 1

    # Logging twice in a day is harmless.
    assert client.post("/api/walks", headers=HEADERS).json()["streak"] == 1

    body = client.delete("/api/walks/today", headers=HEADERS).json()
    assert body["walked"] is False
    assert body["streak"] == 0


def test_streak_survives_until_midnight(client: TestClient, clock: Clock) -> None:
    for days_ago in (3, 2, 1):
        clock.now = datetime(2026, 10, 13, 9, tzinfo=UTC) - timedelta(days=days_ago)
        client.post("/api/walks", headers=HEADERS)

    clock.now = datetime(2026, 10, 13, 22, 14, tzinfo=UTC)
    body = client.get("/api/today", headers=HEADERS).json()
    assert body["walked"] is False
    assert body["streak"] == 3

    assert client.post("/api/walks", headers=HEADERS).json()["streak"] == 4


def test_missing_a_day_resets_streak(client: TestClient, clock: Clock) -> None:
    clock.now = datetime(2026, 10, 11, 9, tzinfo=UTC)
    client.post("/api/walks", headers=HEADERS)
    clock.now = datetime(2026, 10, 13, 9, tzinfo=UTC)
    assert client.get("/api/today", headers=HEADERS).json()["streak"] == 0


def test_users_are_separate(client: TestClient) -> None:
    client.post("/api/walks", headers=HEADERS)
    other = {"X-authentik-username": "sam", "X-authentik-name": "Sam"}
    assert client.get("/api/today", headers=other).json()["walked"] is False


def test_day_boundary_uses_local_time(client: TestClient, clock: Clock) -> None:
    # 23:30 UTC on the 13th is already 00:30 on the 14th in London (BST).
    clock.now = datetime(2026, 10, 13, 23, 30, tzinfo=UTC)
    assert client.get("/api/today", headers=HEADERS).json()["date"] == "2026-10-14"


def test_countdown_on_clock_change_day(client: TestClient, clock: Clock) -> None:
    # 00:30 BST on Sun 25 Oct; clocks go back an hour that night, so the day
    # has 25 hours and 24.5 of them are left.
    clock.now = datetime(2026, 10, 24, 23, 30, tzinfo=UTC)
    body = client.get("/api/today", headers=HEADERS).json()
    assert body["date"] == "2026-10-25"
    assert body["seconds_left"] == int(24.5 * 3600)


def test_serves_frontend(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "Amble" in res.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/api/nope", headers=HEADERS).status_code == 404


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
