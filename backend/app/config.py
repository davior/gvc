"""Every environment-derived setting, resolved once.

Copied from GAM. gecko-notes reads `os.getenv` at module scope in a dozen places, so its
tests monkeypatch module globals and whichever module imported a value first wins. One
settings object avoids that: tests override the object.

Instantiated once as `settings` at the bottom. Import that, not the class.
"""

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# The weak default gecko-notes ships, refused there and refused here. Sharing the
# constant means a copied .env carrying it fails in both apps rather than silently
# signing tokens with a published secret in one of them.
_WEAK_SECRETS = frozenset({
    "",
    "change-me",
    "gecko-notes-secret-change-in-production",
    "gam-secret-change-in-production",
    "gvc-secret-change-in-production",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ─── identity ────────────────────────────────────────────────────────────
    # Must match gecko-notes'. GVC does not issue tokens — it verifies the ones
    # Notes issued, and a shared HS256 secret is what makes that possible. Login is the
    # one thing GVC needs Notes for at runtime.
    #
    # validate_default is load-bearing: pydantic v2 skips validators on defaults, so
    # without it an unset secret would sail past _reject_weak_secret and the app would
    # start up unable to verify anything.
    jwt_secret_key: str = Field(default="", validate_default=True)
    jwt_algorithm: str = "HS256"
    # The cookie gecko-notes sets on the parent domain. Read only; GVC never sets it.
    auth_cookie_name: str = "gecko_session"
    # Where an unauthenticated visitor is sent to sign in.
    notes_base_url: str = "https://notes.geckopico.com"

    # ─── storage ─────────────────────────────────────────────────────────────
    # GVC owns no media — footage, music and renders live in GAM — so a database is
    # all there is to locate.
    database_url: str = ""

    # ─── siblings ────────────────────────────────────────────────────────────
    # The media library. Read from M1 on; set now so a deployment's .env is complete
    # before anything depends on it.
    gam_base_url: str = "https://gam.geckopico.com"

    # ─── http ────────────────────────────────────────────────────────────────
    cors_origin: str = ""

    # ─── administration ──────────────────────────────────────────────────────
    # Comma-separated user ids or usernames, matched exactly. The Notes token carries no
    # admin claim, so this is the only way anybody becomes one. Nothing in M0 is
    # admin-only; it is here so `/api/me` answers the same question GAM's does.
    admin_users: str = ""

    # ─── development ─────────────────────────────────────────────────────────
    # Bypasses token verification and acts as this user id. Refused unless
    # `environment` is "development", so it cannot be switched on in production by
    # setting one variable.
    environment: str = "production"
    dev_auth_user: str = ""

    @field_validator("jwt_secret_key")
    @classmethod
    def _reject_weak_secret(cls, value: str) -> str:
        if value.strip() in _WEAK_SECRETS:
            raise ValueError(
                "JWT_SECRET_KEY must be set to a strong secret before starting. "
                "It must match the value gecko-notes uses, since GVC verifies the "
                "tokens Notes issues. Generate one with: openssl rand -hex 32"
            )
        return value

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{REPO_ROOT / 'data' / 'db' / 'gvc.db'}"

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_origin.split(",") if o.strip()]

    @property
    def admin_user_list(self) -> List[str]:
        return [u.strip() for u in self.admin_users.split(",") if u.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment.strip().lower() in {"development", "dev", "local"}

    @property
    def dev_auth_enabled(self) -> bool:
        """Whether to accept requests with no token at all.

        Two conditions, not one. `DEV_AUTH_USER` alone is not enough: a production
        .env that picked the variable up from a dev template would otherwise turn
        authentication off entirely.
        """
        return bool(self.dev_auth_user) and self.is_development


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
