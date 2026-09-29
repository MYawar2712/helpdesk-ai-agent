"""Application configuration loaded from environment variables via Pydantic Settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings.

    Values are read from environment variables (case-insensitive).
    A `.env` file in the project root is automatically loaded when present.
    Never commit real secrets to source control.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── JWT ──────────────────────────────────────────────────────────────────
    jwt_secret_key: str = Field(
        ...,
        description="Secret used to sign JWT access tokens. Must be set in production.",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm.")
    access_token_expire_minutes: int = Field(
        default=60,
        ge=1,
        description="Lifetime of an access token in minutes.",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite:///db/helpdesk.sqlite3",
        description="SQLAlchemy-compatible database URL.",
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_env: str = Field(default="development", description="Runtime environment name.")
    debug: bool = Field(default=False, description="Enable debug mode.")

    @field_validator("jwt_secret_key", mode="before")
    @classmethod
    def _secret_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("jwt_secret_key must not be empty.")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton instance of Settings.

    Using ``lru_cache`` ensures we only read and parse the environment once
    per process, which keeps startup fast and avoids redundant I/O.
    """
    return Settings()
