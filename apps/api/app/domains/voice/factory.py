"""Builds the real voice platform client from settings. The one place that knows which vendor
is configured; both the API and the worker come here."""

from __future__ import annotations

from app.config import settings
from app.domains.voice.gupshup import GupshupPlatform
from app.domains.voice.platform import VoicePlatform
from app.errors import ApiError


def configured() -> bool:
    return bool(
        settings.gupshup_api_key and settings.gupshup_base_url and settings.voice_tools_base_url
    )


def make_platform() -> VoicePlatform:
    if not (settings.gupshup_api_key and settings.gupshup_base_url):
        raise ApiError(503, "voice_not_configured", "Voice ordering is not set up on this server.")
    return GupshupPlatform(settings.gupshup_base_url, settings.gupshup_api_key)


def tools_base_url() -> str:
    if not settings.voice_tools_base_url:
        raise ApiError(503, "voice_not_configured", "Voice ordering is not set up on this server.")
    return settings.voice_tools_base_url
