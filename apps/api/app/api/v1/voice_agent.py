"""The owner switches the phone ordering agent on and off for an outlet (docs/DECISIONS.md
"Voice provisioning"). Owner only, and only while a platform admin has allowed voice ordering
for the restaurant.

Enabling and disabling return at once (202) with the current state; the platform calls happen
in a background job and the client polls `GET`. Asking twice is harmless. Nothing here shows
the owner a vendor's error text or an id: they get a plain message and the steps."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import clock
from app.api.v1.common import ERRORS, Ctx
from app.core.permissions import Capability, assert_can
from app.core.state import VoiceState
from app.domains.tenant.models import Restaurant
from app.domains.voice import factory, jobs, provisioning
from app.domains.voice.menu_source import load_prompt_menu
from app.domains.voice.models import VoiceAgent
from app.domains.voice.platform import VoicePlatform
from app.domains.voice.status import VoiceView, build_view
from app.errors import ApiError
from app.realtime.hooks import after_commit

router = APIRouter(prefix="/v1/outlets/{outlet_id}/voice-agent", tags=["voice"])


async def get_voice_platform() -> AsyncIterator[VoicePlatform]:
    platform = factory.make_platform()
    try:
        yield platform
    finally:
        close = getattr(platform, "aclose", None)
        if close is not None:
            await close()


Platform = Annotated[VoicePlatform, Depends(get_voice_platform)]


class VoiceStepOut(BaseModel):
    key: str
    label: str
    state: Literal["done", "running", "pending", "failed"]


class VoiceAgentOut(BaseModel):
    allowed: bool  # a platform admin has allowed voice ordering for this restaurant
    phase: Literal["unavailable", "off", "setting_up", "active", "failed", "turning_off"]
    status: str
    enabled: bool
    steps: list[VoiceStepOut]
    phone_number: str | None
    message: str | None
    can_enable: bool
    can_disable: bool
    updated_at: datetime | None


def to_out(view: VoiceView) -> VoiceAgentOut:
    return VoiceAgentOut(
        allowed=view.allowed,
        phase=view.phase,
        status=view.status,
        enabled=view.phase == "active",
        steps=[VoiceStepOut(key=s.key, label=s.label, state=s.state) for s in view.steps],
        phone_number=view.phone_number,
        message=view.message,
        can_enable=view.can_enable,
        can_disable=view.can_disable,
        updated_at=view.updated_at,
    )


async def _restaurant(ctx: Ctx) -> Restaurant:
    restaurant = await ctx.session.get(Restaurant, ctx.restaurant_id)
    assert restaurant is not None
    return restaurant


def _view(row: VoiceAgent | None, restaurant: Restaurant) -> VoiceAgentOut:
    return to_out(build_view(row, restaurant.voice_orders_allowed, restaurant.status == "active"))


@router.get("", responses=ERRORS)
async def get_status(ctx: Ctx) -> VoiceAgentOut:
    """Polled while setting up. Also queues a job again if its message was lost."""
    assert_can(ctx.actor, Capability.ENABLE_VOICE_AGENT, ctx.outlet_id)
    restaurant = await _restaurant(ctx)
    row = await provisioning.get_voice_agent(ctx.session, ctx.outlet_id)
    if row is not None and (kind := provisioning.stale_request(row, clock.utcnow())):
        restaurant_id, outlet_id = ctx.restaurant_id, ctx.outlet_id

        async def again() -> None:
            jobs.enqueue(kind, restaurant_id, outlet_id)

        after_commit(ctx.session, again)
    return _view(row, restaurant)


@router.post("/enable", status_code=202, responses=ERRORS)
async def enable(ctx: Ctx) -> VoiceAgentOut:
    assert_can(ctx.actor, Capability.ENABLE_VOICE_AGENT, ctx.outlet_id)
    restaurant = await _restaurant(ctx)
    if not restaurant.voice_orders_allowed:
        raise ApiError(
            403,
            "voice_not_allowed",
            "Voice ordering is not available for this restaurant. "
            "Please contact your administrator.",
        )
    row = await provisioning.get_voice_agent(ctx.session, ctx.outlet_id)
    starting = row is None or row.status in (
        VoiceState.DISABLED,
        VoiceState.PROVISIONING_FAILED,
    )
    if starting:
        if restaurant.status != "active":
            raise ApiError(409, "restaurant_suspended", "This restaurant is suspended.")
        factory.tools_base_url()  # 503 now if the server is not set up, not after a queued job
        menu = await load_prompt_menu(ctx.session, ctx.restaurant_id, ctx.outlet_id)
        if menu.item_count == 0:
            raise ApiError(
                409, "menu_empty", "Add at least one available menu item before turning on voice."
            )
    row = await provisioning.request_enable(
        ctx.session,
        restaurant_id=ctx.restaurant_id,
        outlet_id=ctx.outlet_id,
        actor=ctx.actor.user_id,
        by_platform_admin=False,
        now=clock.utcnow(),
    )
    return _view(row, restaurant)


@router.post("/disable", status_code=202, responses=ERRORS)
async def disable(ctx: Ctx) -> VoiceAgentOut:
    assert_can(ctx.actor, Capability.ENABLE_VOICE_AGENT, ctx.outlet_id)
    restaurant = await _restaurant(ctx)
    row = await provisioning.get_voice_agent(ctx.session, ctx.outlet_id, lock=True)
    if row is None:
        raise ApiError(409, "voice_not_active", "The voice agent is not on.")
    row = await provisioning.request_disable(
        ctx.session, row, actor=ctx.actor.user_id, by_platform_admin=False, now=clock.utcnow()
    )
    return _view(row, restaurant)


@router.post("/resync", responses=ERRORS)
async def resync(ctx: Ctx, platform: Platform) -> VoiceAgentOut:
    """Rebuilds the agent's prompt from the current menu (call it after a menu change)."""
    assert_can(ctx.actor, Capability.ENABLE_VOICE_AGENT, ctx.outlet_id)
    restaurant = await _restaurant(ctx)
    row = await provisioning.get_voice_agent(ctx.session, ctx.outlet_id)
    if row is None:
        raise ApiError(409, "voice_not_active", "The voice agent is not on.")
    menu = await load_prompt_menu(ctx.session, ctx.restaurant_id, ctx.outlet_id)
    row = await provisioning.resync(
        ctx.session, platform, row, menu, factory.tools_base_url(), clock.utcnow()
    )
    return _view(row, restaurant)
