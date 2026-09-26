from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app_dev"
    # Owner role for Alembic and test seeding; falls back to database_url.
    migration_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    # Namespaces our Redis keys so stacks (or a test run) sharing one Redis never drain each other.
    redis_key_prefix: str = "restosaas"
    jwt_secret: str = "dev-only-change-me-not-for-production-0123456789"
    jwt_issuer: str = "restosaas-api"
    jwt_access_token_ttl_seconds: int = 3600
    app_db_role: str = "app"
    environment: str = "development"
    log_level: str = "INFO"
    otp_dev_mode: bool = True
    # Browser tests cannot read the console, so they set a fixed code. Refused in production.
    otp_dev_fixed_code: str | None = None
    # Where QR codes and staff invite links point. Product domain is undecided (SPEC §12).
    public_base_url: str = "http://localhost:3000"
    staff_base_url: str = "http://localhost:3001"
    invite_ttl_days: int = 7
    # Voice ordering agent (docs/DECISIONS.md "Voice ordering agent"). The key comes from the
    # environment only. `voice_tools_base_url` is where the platform can reach this API.
    gupshup_api_key: str | None = None
    gupshup_base_url: str | None = None
    voice_tools_base_url: str | None = None
    # The one SR number the enable flow may link (else the first unlinked one). Never a linked one.
    voice_sr_number: str | None = None
    # Object storage for uploaded menus (docs/DECISIONS.md "Menu import from PDF or photos").
    # Any S3-compatible service: MinIO locally, S3 later by changing these values only.
    storage_endpoint_url: str | None = "http://localhost:9010"
    storage_access_key: str = "minioadmin"
    storage_secret_key: str = "minioadmin"
    storage_bucket: str = "restosaas-uploads"
    storage_region: str = "us-east-1"
    # Menu extraction. The provider is chosen by name; the key comes from the environment only.
    menu_extraction_provider: str = "openai"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    menu_extraction_model: str = "gpt-4o"
    menu_extraction_timeout_seconds: float = 90.0
    menu_extraction_max_attempts: int = 3
    menu_extraction_max_files: int = 20
    menu_extraction_max_pages: int = 40
    menu_extraction_max_file_bytes: int = 15_000_000
    # A PDF page with fewer characters than this has no usable text layer and is read as an image.
    menu_extraction_min_text_chars: int = 40
    # Longest image side sent to the model. Smaller than this is never enlarged.
    menu_extraction_max_image_px: int = 2000
    # Estimated cost, USD per million tokens (gpt-4o list price). Reporting only.
    menu_extraction_input_usd_per_mtok: float = 2.5
    menu_extraction_output_usd_per_mtok: float = 10.0
    # Browser origins allowed to call the API (the three Next.js apps).
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
    ]

    @model_validator(mode="after")
    def _no_fixed_otp_in_production(self) -> Settings:
        if self.otp_dev_fixed_code is not None and self.environment == "production":
            raise ValueError("OTP_DEV_FIXED_CODE must not be set when ENVIRONMENT=production")
        return self


settings = Settings()
