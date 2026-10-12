from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
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
    # Google redirects here; it goes through the Next.js /api proxy so the session cookie is first-party.
    google_redirect_uri: str = "http://localhost:3000/api/auth/google/callback"
    frontend_url: str = "http://localhost:3000"
    admin_emails: list[str] = Field(default_factory=list)  # always allowed to sign in, and admins

    send_jitter_min_minutes: int = 3
    send_jitter_max_minutes: int = 12

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
    embed_min_sim: float = 0.6  # bge-small: unrelated jobs score ~0.55, related ones 0.65+
    # Downloaded model files (~65 MB). docker-compose mounts a volume here so restarts don't re-download.
    embed_cache_dir: str = str(Path.home() / ".cache" / "sherlock" / "models")

    # Matching (PLAN.md Phase 3). The fast model's free tier is ~20 requests/day per key, shared with
    # resume parsing, so scoring gets a per-user daily allowance of batched requests.
    match_batch_size: int = 10
    match_candidates_per_run: int = 50
    match_daily_llm_calls: int = 6
    # Open outreach (PLAN.md Phase 8): companies are scored the same way, under a smaller allowance.
    company_match_batch_size: int = 8
    company_candidates_per_run: int = 24
    company_match_daily_llm_calls: int = 3
    company_min_sim: float = 0.0  # rank by similarity only; the LLM decides

    hn_enabled: bool = True  # parse HN "Who is hiring" with the owner's key (needs GEMINI_API_KEY)

    hunter_api_key: str = ""  # owner's key; used for other users only if the fallback below is on
    allow_owner_hunter_fallback: bool = False
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    max_contact_lookups_per_user_month: int = 40
    contact_cache_days: int = 60
    max_llm_usd_per_user_month: float = 5.0
    # Estimated cost of one LLM request, logged to usage_ledger. 0 on Gemini's free tier; set it when a
    # paid model or provider is used so MAX_LLM_USD_PER_USER_MONTH means something.
    llm_usd_per_call: float = 0.0

    # API rate limit (PLAN.md Phase 9): a Redis token bucket per signed-in user (per IP otherwise).
    api_rate_limit_enabled: bool = True
    api_rate_per_minute: int = 120
    api_rate_burst: int = 60

    log_json: bool = False  # JSON lines (one object per record); on by default in production
    sentry_dsn: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def _comment_only_is_unset(cls, value: object) -> object:
        """`KEY=   # note` reaches the app as "# note" through docker compose's env_file (pydantic's
        own .env reader strips it). A value that is only a comment means the key is unset."""
        if isinstance(value, str) and value.strip().startswith("#"):
            return ""
        return value

    @model_validator(mode="after")
    def _check_production_safety(self) -> "Settings":
        if self.env == "production" and self.dev_auth:
            raise ValueError("DEV_AUTH=true is not allowed when ENV=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
