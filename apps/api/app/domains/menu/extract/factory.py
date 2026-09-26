"""Builds the configured extraction provider. The one place that knows which vendors exist."""

from __future__ import annotations

from app.config import settings
from app.domains.menu.extract.openai_provider import OpenAIProvider
from app.domains.menu.extract.provider import MenuExtractionProvider
from app.errors import ApiError

_NOT_CONFIGURED = ApiError(
    503, "menu_extraction_not_configured", "Reading menus from files is not set up on this server."
)


def configured() -> bool:
    if settings.menu_extraction_provider == "openai":
        return bool(settings.openai_api_key)
    return False


def make_provider() -> MenuExtractionProvider:
    if settings.menu_extraction_provider == "openai" and settings.openai_api_key:
        return OpenAIProvider(
            settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.menu_extraction_model,
            timeout=settings.menu_extraction_timeout_seconds,
        )
    raise _NOT_CONFIGURED
