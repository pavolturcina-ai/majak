"""Application settings, loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Anthropic / LLM ──────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    claude_model_extract: str = "claude-sonnet-4-5"
    claude_model_synth: str = "claude-opus-4-1"
    claude_model_vision: str = "claude-sonnet-4-5"

    # ── Supabase ─────────────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_service_key: str = ""
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
    supabase_storage_bucket: str = "majak-sources"
    supabase_jwt_secret: str = ""

    # ── Auth ─────────────────────────────────────────────────────────────
    auth_single_user_email: str = "pavol.turcina@gospace.tech"

    # ── Connectors ───────────────────────────────────────────────────────────
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    # Extra Gmail search filter (same operators as the Gmail box), e.g.
    # "is:starred", "in:inbox is:unread", "is:important". Empty = all mail.
    gmail_query: str = ""
    slack_bot_token: str = ""
    slack_user_token: str = ""
    slack_app_token: str = ""
    fathom_api_key: str = ""
    gcal_client_id: str = ""
    gcal_client_secret: str = ""
    gcal_refresh_token: str = ""
    gcal_calendar_id: str = "primary"

    # ── Runtime ──────────────────────────────────────────────────────────────
    tz: str = "Europe/Bratislava"
    run_times: str = "18:00,04:00"
    notify_channel: str = "log"
    notify_target: str = "pavol.turcina@gospace.tech"
    # Shared secret the pg_cron / edge-function caller presents to /scheduler/*.
    cron_secret: str = "dev-cron-secret"
    # Shared bearer token for the single user's frontend (works alongside JWT).
    # Set this to let the hosted report/import authenticate without a login flow.
    app_token: str = ""

    # ── People resolution thresholds ────────────────────────────────────────
    person_match_link: float = Field(default=0.92, ge=0, le=1)
    person_match_review: float = Field(default=0.75, ge=0, le=1)

    # ── Embeddings ───────────────────────────────────────────────────────────
    embedding_dim: int = 1024

    @property
    def close_time(self) -> str:
        return self.run_times.split(",")[0].strip()

    @property
    def fill_time(self) -> str:
        parts = self.run_times.split(",")
        return parts[1].strip() if len(parts) > 1 else "04:00"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
