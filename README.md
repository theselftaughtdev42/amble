# amble

Simple web app for tracking daily walking.

One screen: a countdown to midnight, a big "I walked today" button, and a streak that keeps counting for as long as you keep walking. Logging a walk plays a little footsteps animation.

## How it works

- **Backend:** FastAPI with a SQLite file (one row per user per day walked).
- **Frontend:** plain HTML, CSS and JS in `frontend/`, served by FastAPI's `app.frontend()` (FastAPI 0.138+). API routes always take priority over the static files.
- **Sign-in:** OpenID Connect via [Authlib](https://authlib.org), against any standards-compliant provider (authentik, Keycloak, Auth0, Okta, Entra ID, Google, …). Amble runs the authorization code flow with PKCE itself and keeps the signed-in user in a signed session cookie. Each person's walks are keyed by the `sub` claim. The initials badge uses the first of `name`, `preferred_username` or `email`; if the ID token has none of them, Amble asks the provider's userinfo endpoint.
- **Days:** "today", the countdown and streaks all use `AMBLE_TZ` (default `Europe/London`), clock changes included. A streak stays alive until midnight, so not having walked *yet* today doesn't break it.

## API

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/me` | Signed-in name and initials |
| `GET` | `/api/today` | Today's date, whether it's walked, the streak and seconds until midnight |
| `POST` | `/api/walks` | Log today's walk (safe to repeat) |
| `DELETE` | `/api/walks/today` | Undo today's walk |
| `GET` | `/auth/login` | Start sign-in at the OIDC provider |
| `GET` | `/auth/callback` | OIDC redirect URI |
| `GET` | `/auth/logout` | Sign out (and at the provider, if it supports RP-initiated logout) |
| `GET` | `/healthz` | Health check, no sign-in needed |

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `AMBLE_DB` | `data/amble.db` (`/data/amble.db` in Docker) | SQLite file path |
| `AMBLE_TZ` | `Europe/London` | Time zone for days and the countdown |
| `AMBLE_OIDC_ISSUER` | unset | The provider's issuer URL; `/.well-known/openid-configuration` is read from under it |
| `AMBLE_OIDC_CLIENT_ID` | unset | Required with `AMBLE_OIDC_ISSUER` |
| `AMBLE_OIDC_CLIENT_SECRET` | unset | Required with `AMBLE_OIDC_ISSUER` |
| `AMBLE_SESSION_SECRET` | unset | Signs the session cookie. Required with `AMBLE_OIDC_ISSUER`; a long random string that stays the same across restarts |
| `AMBLE_PUBLIC_URL` | unset | e.g. `https://amble.example.com`. Used to build the callback and logout URLs, and marks the cookie `Secure` when it's `https`. Set it when running behind a reverse proxy |
| `AMBLE_OIDC_SCOPE` | `openid profile email` | Scopes to request |
| `AMBLE_OIDC_TOKEN_AUTH_METHOD` | `client_secret_basic` | How the client secret is sent to the token endpoint: `client_secret_basic` or `client_secret_post` |
| `AMBLE_DEV_USER` | unset | Display name to use when nobody is signed in. **Local development only.** |

The app refuses to start unless either `AMBLE_OIDC_ISSUER` or `AMBLE_DEV_USER` is set.

## Run locally

The project is managed with [uv](https://docs.astral.sh/uv/).

```sh
uv sync
AMBLE_DEV_USER="Jane Doe" uv run uvicorn --factory app.main:create_app --reload
```

Then open http://localhost:8000. Run the tests with `uv run pytest`.

Add a dependency with `uv add <package>` (or `uv add --dev <package>` for dev-only tools); commit `pyproject.toml` and `uv.lock` together.

## Releases

Releases are published by pushing a version tag on `main`:

```sh
git tag v1.2.3 && git push origin v1.2.3
```

CI tests, builds and publishes the image as `ghcr.io/theselftaughtdev42/amble:<version>` (e.g. `ghcr.io/theselftaughtdev42/amble:1.2.3`). Tags that aren't on `main` are refused. Pull requests build the image without pushing it. Pushes to `main` also publish `main` and `sha-<commit>` tags for testing. There is no `latest` tag.

The image serves the app on `0.0.0.0:8000`; the health endpoint is `/healthz`.

## Deploy

Pin an exact version:

```sh
docker run -d --name amble -v amble-data:/data -p 127.0.0.1:8000:8000 \
  -e AMBLE_PUBLIC_URL=https://amble.example.com \
  -e AMBLE_OIDC_ISSUER=https://auth.example.com/application/o/amble/ \
  -e AMBLE_OIDC_CLIENT_ID=... -e AMBLE_OIDC_CLIENT_SECRET=... \
  -e AMBLE_SESSION_SECRET="$(openssl rand -hex 32)" \
  ghcr.io/theselftaughtdev42/amble:1.2.3
```

Register Amble with your OIDC provider as a confidential web application (authorization code flow):

- **Redirect URI:** `https://amble.example.com/auth/callback`
- **Post-logout redirect URI** (optional): `https://amble.example.com/`, so signing out comes back to Amble
- **Scopes:** `openid profile email`

Put a TLS-terminating reverse proxy in front of the container. If the provider advertises an `end_session_endpoint`, `/auth/logout` signs the person out there too; otherwise it only ends the Amble session.
