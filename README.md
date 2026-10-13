# amble

Simple web app for tracking daily walking.

One screen: a countdown to midnight, a big "I walked today" button, and a streak that keeps counting for as long as you keep walking. Logging a walk plays a little footsteps animation.

## How it works

- **Backend:** FastAPI with a SQLite file (one row per user per day walked).
- **Frontend:** plain HTML, CSS and JS in `frontend/`, served by FastAPI's `app.frontend()` (FastAPI 0.138+). API routes always take priority over the static files.
- **Sign-in:** handled entirely by [authentik](https://goauthentik.io) in front of the app. Its proxy outpost adds `X-authentik-username` and `X-authentik-name` headers to each request; Amble uses the username to keep each person's walks separate and the name for the initials badge.
- **Days:** "today", the countdown and streaks all use `AMBLE_TZ` (default `Europe/London`), clock changes included. A streak stays alive until midnight, so not having walked *yet* today doesn't break it.

## API

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/me` | Signed-in name and initials |
| `GET` | `/api/today` | Today's date, whether it's walked, the streak and seconds until midnight |
| `POST` | `/api/walks` | Log today's walk (safe to repeat) |
| `DELETE` | `/api/walks/today` | Undo today's walk |
| `GET` | `/healthz` | Health check, no sign-in needed |

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `AMBLE_DB` | `data/amble.db` (`/data/amble.db` in Docker) | SQLite file path |
| `AMBLE_TZ` | `Europe/London` | Time zone for days and the countdown |
| `AMBLE_DEV_USER` | unset | Display name to use when there are no authentik headers. **Local development only.** |

## Run locally

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
AMBLE_DEV_USER="Jane Doe" uvicorn --factory app.main:create_app --reload
```

Then open http://localhost:8000. Run the tests with `pytest`.

## Deploy

```sh
docker build -t amble .
docker run -d --name amble -v amble-data:/data -p 127.0.0.1:8000:8000 amble
```

Put it behind an authentik **Proxy Provider** (or forward auth through your reverse proxy) pointing at the container.

> **Important:** Amble trusts the `X-authentik-*` headers. Make sure the container is only reachable through authentik (bind it to localhost or an internal Docker network), otherwise anyone could send those headers themselves.
