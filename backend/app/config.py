"""Application settings, read once from the environment at import time."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Database ---------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://ledger:ledger@localhost:5432/ledger",
        alias="DATABASE_URL",
    )
    run_migrations_on_start: bool = Field(default=True, alias="RUN_MIGRATIONS_ON_START")

    # --- Security ---------------------------------------------------------
    secret_key: str = Field(default="dev-only-insecure-key", alias="SECRET_KEY")
    access_token_expire_minutes: int = Field(
        default=20160, alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    session_cookie_name: str = Field(default="ledger_session", alias="SESSION_COOKIE_NAME")
    # Set to false only when serving over plain HTTP on a trusted LAN.
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")

    # --- Bootstrap owner --------------------------------------------------
    bootstrap_admin_email: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_EMAIL")
    bootstrap_admin_password: str | None = Field(
        default=None, alias="BOOTSTRAP_ADMIN_PASSWORD"
    )
    bootstrap_admin_name: str = Field(default="Owner", alias="BOOTSTRAP_ADMIN_NAME")

    # --- Money ------------------------------------------------------------
    base_currency: str = Field(default="RON", alias="BASE_CURRENCY")
    supported_currencies: str = Field(default="RON,EUR,USD", alias="SUPPORTED_CURRENCIES")

    # --- Storage ----------------------------------------------------------
    storage_dir: str = Field(default="./data/uploads", alias="STORAGE_DIR")
    max_upload_mb: int = Field(default=25, alias="MAX_UPLOAD_MB")
    image_max_edge: int = Field(default=1800, alias="IMAGE_MAX_EDGE")
    thumb_max_edge: int = Field(default=400, alias="THUMB_MAX_EDGE")

    # --- Local AI ---------------------------------------------------------
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_vision_model: str = Field(default="qwen2.5vl:7b", alias="OLLAMA_VISION_MODEL")
    ollama_timeout_seconds: int = Field(default=300, alias="OLLAMA_TIMEOUT_SECONDS")

    # --- Worker -----------------------------------------------------------
    worker_poll_seconds: int = Field(default=5, alias="WORKER_POLL_SECONDS")
    worker_max_attempts: int = Field(default=3, alias="WORKER_MAX_ATTEMPTS")
    # Below this the scan is flagged for a human instead of being trusted.
    review_confidence_threshold: float = Field(
        default=0.75, alias="REVIEW_CONFIDENCE_THRESHOLD"
    )

    @field_validator("base_currency")
    @classmethod
    def _upper_base(cls, v: str) -> str:
        return v.strip().upper()

    @property
    def currencies(self) -> list[str]:
        """Supported currency codes, base currency guaranteed first."""
        codes = [c.strip().upper() for c in self.supported_currencies.split(",") if c.strip()]
        if self.base_currency in codes:
            codes.remove(self.base_currency)
        return [self.base_currency, *codes]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
