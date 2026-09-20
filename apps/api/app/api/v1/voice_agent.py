"""The owner switches the phone ordering agent on and off for an outlet (docs/DECISIONS.md
"Voice ordering agent"). Owner only. Enabling creates the agent on the voice platform from
this restaurant's own menu and links a phone number; the tool key never leaves the server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import clock
from app.api.v1.common import ERRORS, Ctx
from app.api.v1.guest import build_guest_menu
from app.audit import audit
from app.config import settings
from app.core.permissions import Capability, assert_can
from app.domains.tenant.models import Restaurant
from app.domains.voice import provisioning
from app.domains.voice.gupshup import GupshupPlatform
from app.domains.voice.models import VoiceAgent
from app.domains.voice.platform import VoicePlatform
from app.domains.voice.prompt import (
    PromptCategory,
    PromptItem,
    PromptMenu,
    PromptModifier,
    PromptModifierGroup,
)
from app.errors import ApiError

router = APIRouter(prefix="/v1/outlets/{outlet_id}/voice-agent", tags=["voice"])


async def get_voice_platform() -> AsyncIterator[VoicePlatform]:
    if not (settings.gupshup_api_key and settings.gupshup_base_url):
        raise ApiError(503, "voice_not_configured", "Voice ordering is not set up on this server.")
    platform = GupshupPlatform(settings.gupshup_base_url, settings.gupshup_api_key)
    try:
        yield platform
    finally:
        await platform.aclose()


Platform = Annotated[VoicePlatform, Depends(get_voice_platform)]


class VoiceAgentOut(BaseModel):
    enabled: bool
    status: str  # off | pending | active | disabled | failed
    phone_number: str | None
    last_error: str | None
    updated_at: datetime | None


def _out(row: VoiceAgent | None) -> VoiceAgentOut:
    if row is None:
        return VoiceAgentOut(
            enabled=False, status="off", phone_number=None, last_error=None, updated_at=None
        )
    return VoiceAgentOut(
        enabled=row.status == "active",
        status=row.status,
        phone_number=row.phone_number,
        last_error=row.last_error,
        updated_at=row.updated_at,
    )


def _tools_base_url() -> str:
    if not settings.voice_tools_base_url:
        raise ApiError(503, "voice_not_configured", "Voice ordering is not set up on this server.")
    return settings.voice_tools_base_url


async def _prompt_menu(ctx: Ctx) -> PromptMenu:
    """Only what a caller could really order: listed, in stock, and not gated behind a manager's
    approval (a phone call cannot get that approval)."""
    restaurant = await ctx.session.get(Restaurant, ctx.restaurant_id)
    assert restaurant is not None
    menu = await build_guest_menu(ctx.session, ctx.outlet_id, clock.utcnow())
    categories: list[PromptCategory] = []
    for category in menu.categories:
        items = tuple(
            PromptItem(
                id=item.id,
                name=item.name,
                price_paise=item.price_paise,
                veg=item.veg,
                description=item.description,
                modifier_groups=tuple(
                    PromptModifierGroup(
                        name=g.name,
                        min_select=g.min_select,
                        max_select=g.max_select,
                        modifiers=tuple(
                            PromptModifier(m.id, m.name, m.price_delta_paise) for m in g.modifiers
                        ),
                    )
                    for g in item.modifier_groups
                ),
            )
            for item in category.items
            if item.available and item.self_orderable
        )
        if items:
            categories.append(PromptCategory(category.name, items))
    return PromptMenu(restaurant.brand_name, tuple(categories))


@router.get("", responses=ERRORS)
async def get_status(ctx: Ctx) -> VoiceAgentOut:
    assert_can(ctx.actor, Capability.ENABLE_VOICE_AGENT, ctx.outlet_id)
    return _out(await provisioning.get_voice_agent(ctx.session, ctx.outlet_id))


@router.post("/enable", responses=ERRORS)
async def enable(ctx: Ctx, platform: Platform) -> VoiceAgentOut:
    assert_can(ctx.actor, Capability.ENABLE_VOICE_AGENT, ctx.outlet_id)
    menu = await _prompt_menu(ctx)
    if menu.item_count == 0:
        raise ApiError(
            409, "menu_empty", "Add at least one available menu item before turning on voice."
        )
    row = await provisioning.enable(
        ctx.session,
        platform,
        restaurant_id=ctx.restaurant_id,
        outlet_id=ctx.outlet_id,
        user_id=ctx.actor.user_id,
        menu=menu,
        tools_base_url=_tools_base_url(),
        preferred_number=settings.voice_sr_number,
        now=clock.utcnow(),
    )
    audit(ctx, "voice.enabled", "voice_agent", row.id, after={"status": row.status})
    return _out(row)


@router.post("/disable", responses=ERRORS)
async def disable(ctx: Ctx, platform: Platform) -> VoiceAgentOut:
    assert_can(ctx.actor, Capability.ENABLE_VOICE_AGENT, ctx.outlet_id)
    row = await provisioning.get_voice_agent(ctx.session, ctx.outlet_id)
    if row is None or row.status != "active":
        raise ApiError(409, "voice_not_active", "The voice agent is not on.")
    row = await provisioning.disable(ctx.session, platform, row, clock.utcnow())
    audit(ctx, "voice.disabled", "voice_agent", row.id, after={"status": row.status})
    return _out(row)


@router.post("/resync", responses=ERRORS)
async def resync(ctx: Ctx, platform: Platform) -> VoiceAgentOut:
    """Rebuilds the agent's prompt from the current menu (call it after a menu change)."""
    assert_can(ctx.actor, Capability.ENABLE_VOICE_AGENT, ctx.outlet_id)
    row = await provisioning.get_voice_agent(ctx.session, ctx.outlet_id)
    if row is None:
        raise ApiError(409, "voice_not_active", "The voice agent is not on.")
    menu = await _prompt_menu(ctx)
    row = await provisioning.resync(
        ctx.session, platform, row, menu, _tools_base_url(), clock.utcnow()
    )
    return _out(row)
