from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Every field maps to an env var from PLAN.md §11."""

    # Repo-root .env when running from backend/, or a local one.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+asyncpg://sherlock:sherlock@localhost:5433/sherlock"
    redis_url: str = "redis://localhost:6380/0"
    storage_dir: str = "/data/files"
    # Repo-root data/ (skills aliases, company seed). docker-compose mounts it and sets DATA_DIR.
    data_dir: str = str(Path(__file__).resolve().parents[3] / "data")
    max_upload_bytes: int = 5 * 1024 * 1024
    fernet_key: str = ""

    dev_auth: bool = False
    dev_user_email: str = "dev@sherlock.local"
    auth_secret: str = ""
    session_ttl_hours: int = 24 * 7
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    google_client_id: str = ""
    google_client_secret: str = ""

    use_fakes: bool = False
    llm_provider: Literal["gemini", "anthropic"] = "gemini"
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    llm_model_smart: str = "gemini-3.8-flash"
    llm_model_fast: str = "gemini-3.5-flash-lite"
    llm_rpm: int = 4
    llm_rpd: int = 18
    llm_cache_ttl_seconds: int = 7 * 24 * 3600
    allow_owner_key_fallback: bool = False

    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_min_sim: float = 0.35

    hn_enabled: bool = True  # parse HN "Who is hiring" with the owner's key (needs GEMINI_API_KEY)

    hunter_api_key: str = ""
    apollo_api_key: str = ""
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    max_contact_lookups_per_user_month: int = 40
    max_llm_usd_per_user_month: float = 5.0

    sentry_dsn: str = ""

    @model_validator(mode="after")
    def _check_production_safety(self) -> "Settings":
        if self.env == "production" and self.dev_auth:
            raise ValueError("DEV_AUTH=true is not allowed when ENV=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
