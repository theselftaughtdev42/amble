from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TOKEN_AUTH_METHODS = ("client_secret_basic", "client_secret_post")


@dataclass(frozen=True)
class OIDCSettings:
    """The OpenID Connect provider Amble signs people in with."""

    # The provider's issuer URL; its discovery document is read from under it.
    issuer: str
    client_id: str
    client_secret: str
    # Signs the session cookie. Any long random string; keep it stable.
    session_secret: str
    scope: str = "openid profile email"
    # How the client secret goes to the token endpoint: client_secret_basic
    # (Authlib's default, when None) or client_secret_post.
    token_auth_method: str | None = None

    @property
    def metadata_url(self) -> str:
        return self.issuer.rstrip("/") + "/.well-known/openid-configuration"


@dataclass(frozen=True)
class Settings:
    """Runtime configuration, read from AMBLE_* environment variables."""

    db_path: Path = ROOT / "data" / "amble.db"
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/London"))
    oidc: OIDCSettings | None = None
    # Public base URL, e.g. https://amble.example.com. Used for the OIDC
    # callback and logout URLs; when unset they come from the request.
    public_url: str | None = None
    # Display name used when nobody is signed in. Only set this for local
    # development: it lets anyone in without signing in.
    dev_user: str | None = None
    frontend_dir: Path = ROOT / "frontend"

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        env = os.environ.get
        oidc = None
        if env("AMBLE_OIDC_ISSUER"):
            missing = [
                name
                for name in (
                    "AMBLE_OIDC_CLIENT_ID",
                    "AMBLE_OIDC_CLIENT_SECRET",
                    "AMBLE_SESSION_SECRET",
                )
                if not env(name)
            ]
            if missing:
                raise RuntimeError(f"AMBLE_OIDC_ISSUER is set but {', '.join(missing)} is not")
            oidc = OIDCSettings(
                issuer=env("AMBLE_OIDC_ISSUER"),
                client_id=env("AMBLE_OIDC_CLIENT_ID"),
                client_secret=env("AMBLE_OIDC_CLIENT_SECRET"),
                session_secret=env("AMBLE_SESSION_SECRET"),
                scope=env("AMBLE_OIDC_SCOPE") or "openid profile email",
                token_auth_method=env("AMBLE_OIDC_TOKEN_AUTH_METHOD") or None,
            )
            if oidc.token_auth_method not in (None, *TOKEN_AUTH_METHODS):
                raise RuntimeError(
                    f"AMBLE_OIDC_TOKEN_AUTH_METHOD must be one of {', '.join(TOKEN_AUTH_METHODS)}"
                )
        return cls(
            db_path=Path(env("AMBLE_DB", defaults.db_path)),
            tz=ZoneInfo(env("AMBLE_TZ", "Europe/London")),
            oidc=oidc,
            public_url=(env("AMBLE_PUBLIC_URL") or "").rstrip("/") or None,
            dev_user=env("AMBLE_DEV_USER") or None,
        )
