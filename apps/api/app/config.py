from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app_dev"
    # Owner role for Alembic and test seeding; falls back to database_url.
    migration_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-only-change-me-not-for-production-0123456789"
    jwt_issuer: str = "restosaas-api"
    jwt_access_token_ttl_seconds: int = 3600
    app_db_role: str = "app"
    environment: str = "development"
    log_level: str = "INFO"
    otp_dev_mode: bool = True
    # Where QR codes and staff invite links point. Product domain is undecided (SPEC §12).
    public_base_url: str = "http://localhost:3000"
    staff_base_url: str = "http://localhost:3001"
    invite_ttl_days: int = 7


settings = Settings()
