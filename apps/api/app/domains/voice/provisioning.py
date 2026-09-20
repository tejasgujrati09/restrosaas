"""Switching a restaurant's phone ordering agent on and off (docs/DECISIONS.md "Voice ordering
agent"). Talks to the voice platform only through `VoicePlatform`.

A platform failure is recorded on the `voice_agent` row (status `failed`, a safe message) and
returned, not raised: the request must still commit that row, or the owner would see nothing.
Problems found before any platform call (no number free, a number already in use) are raised.

Never takes a phone number that is already linked to an agent. The number is the customer's
front door, and linking it here would silently cut off whatever it served before.
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.voice.auth import new_voice_key
from app.domains.voice.models import VoiceAgent
from app.domains.voice.platform import (
    AgentSpec,
    PhoneNumber,
    VoicePlatform,
    VoicePlatformError,
)
from app.domains.voice.prompt import PromptMenu, build_agent_prompt
from app.domains.voice.tools import CALLER_VARIABLE, build_tools
from app.errors import ApiError

logger = structlog.get_logger()


async def get_voice_agent(session: AsyncSession, outlet_id: UUID) -> VoiceAgent | None:
    agent: VoiceAgent | None = await session.scalar(
        select(VoiceAgent).where(VoiceAgent.outlet_id == outlet_id)
    )
    return agent


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number)


def pick_number(numbers: list[PhoneNumber], preferred: str | None) -> PhoneNumber:
    """The number to link. A requested number must exist and be unlinked; otherwise the first
    unlinked one. A linked number is never chosen."""
    if preferred:
        match = next((n for n in numbers if _digits(n.number) == _digits(preferred)), None)
        if match is None:
            raise ApiError(409, "number_unavailable", "That phone number is not on the account.")
        if match.linked_agent_id is not None:
            raise ApiError(
                409,
                "number_in_use",
                "That phone number is already linked to another agent. Unlink it first, or "
                "choose a different number.",
            )
        return match
    free = next((n for n in numbers if n.linked_agent_id is None), None)
    if free is None:
        raise ApiError(409, "no_number_available", "There is no free phone number to assign.")
    return free


def _spec(name: str, menu: PromptMenu, base_url: str, key: str, *, active: bool) -> AgentSpec:
    prompt, first_message = build_agent_prompt(menu)
    return AgentSpec(
        name=name,
        description="Phone ordering agent (managed by the restaurant platform).",
        system_prompt=prompt,
        first_message=first_message,
        tools=build_tools(base_url, key),
        call_variables=(CALLER_VARIABLE,),
        active=active,
    )


def agent_name(menu: PromptMenu) -> str:
    return f"{menu.restaurant_name} phone orders"[:120]


def _safe(exc: VoicePlatformError) -> str:
    return f"{exc.op} failed" + (f" (HTTP {exc.status})" if exc.status else "")


async def enable(
    session: AsyncSession,
    platform: VoicePlatform,
    *,
    restaurant_id: UUID,
    outlet_id: UUID,
    user_id: UUID,
    menu: PromptMenu,
    tools_base_url: str,
    preferred_number: str | None,
    now: datetime,
) -> VoiceAgent:
    row = await get_voice_agent(session, outlet_id)
    if row is not None and row.status == "active":
        raise ApiError(409, "voice_already_enabled", "The voice agent is already on.")

    if row is not None and row.status == "disabled" and row.gupshup_agent_id:
        return await _reactivate(session, platform, row, menu, tools_base_url, now)

    key, key_hash = new_voice_key(restaurant_id)
    name = agent_name(menu)
    number = pick_number(await platform.list_numbers(), preferred_number)

    if row is None:
        row = VoiceAgent(
            restaurant_id=restaurant_id,
            outlet_id=outlet_id,
            status="pending",
            key_hash=key_hash,
            enabled_by=user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:  # a previous attempt failed: start clean
        await _discard_platform_agent(platform, row)
        row.status = "pending"
        row.key_hash = key_hash
        row.enabled_by = user_id
    row.updated_at = now
    row.last_error = None

    agent_id: str | None = None
    try:
        agent_id = await platform.create_agent(_spec(name, menu, tools_base_url, key, active=True))
        row.gupshup_agent_id = agent_id
        # Linking is last on purpose: if anything before it fails, no number is left pointing at
        # an agent we then delete.
        await platform.pass_caller_to_agent(number.plan_id)
        await platform.link_number(number.plan_id, agent_id, name, number.number)
    except VoicePlatformError as exc:
        logger.warning("voice_enable_failed", op=exc.op, status=exc.status)
        row.status = "failed"
        row.last_error = _safe(exc)
        await _discard_platform_agent(platform, row)
        await session.flush()
        return row
    row.sr_plan_id = number.plan_id
    row.phone_number = number.number
    row.status = "active"
    await session.flush()
    return row


async def _discard_platform_agent(platform: VoicePlatform, row: VoiceAgent) -> None:
    """Best effort: a half-made agent must not linger. If it cannot be deleted its id stays on
    the row so it can be cleaned up by hand."""
    if not row.gupshup_agent_id:
        return
    try:
        await platform.delete_agent(row.gupshup_agent_id)
    except VoicePlatformError:
        row.last_error = (row.last_error or "") + " (could not remove the half-made agent)"
        return
    row.gupshup_agent_id = None


async def _reactivate(
    session: AsyncSession,
    platform: VoicePlatform,
    row: VoiceAgent,
    menu: PromptMenu,
    tools_base_url: str,
    now: datetime,
) -> VoiceAgent:
    assert row.gupshup_agent_id is not None
    key, key_hash = new_voice_key(row.restaurant_id)
    try:
        await platform.update_agent(
            row.gupshup_agent_id,
            _spec(agent_name(menu), menu, tools_base_url, key, active=True),
        )
    except VoicePlatformError as exc:
        row.status = "failed"
        row.last_error = _safe(exc)
        row.updated_at = now
        await session.flush()
        return row
    row.key_hash = key_hash
    row.status = "active"
    row.last_error = None
    row.updated_at = now
    await session.flush()
    return row


async def disable(
    session: AsyncSession, platform: VoicePlatform, row: VoiceAgent, now: datetime
) -> VoiceAgent:
    """Stops the agent answering and revokes its tool key. The number stays linked and the
    order history is kept. If the platform cannot be reached the tools are still cut off
    (status is what they check), and the error is recorded."""
    row.status = "disabled"
    row.updated_at = now
    row.last_error = None
    if row.gupshup_agent_id:
        try:
            await platform.set_agent_active(row.gupshup_agent_id, False)
        except VoicePlatformError as exc:
            row.last_error = f"{_safe(exc)}; tools are off but the agent may still answer"
    await session.flush()
    return row


async def resync(
    session: AsyncSession,
    platform: VoicePlatform,
    row: VoiceAgent,
    menu: PromptMenu,
    tools_base_url: str,
    now: datetime,
) -> VoiceAgent:
    """Rebuilds the prompt from the current menu. Rotates the tool key, because only its hash
    is stored, so the new key can be sent to the agent but the old one cannot be read back."""
    if row.status != "active" or not row.gupshup_agent_id:
        raise ApiError(409, "voice_not_active", "The voice agent is not on.")
    key, key_hash = new_voice_key(row.restaurant_id)
    try:
        await platform.update_agent(
            row.gupshup_agent_id,
            _spec(agent_name(menu), menu, tools_base_url, key, active=True),
        )
    except VoicePlatformError as exc:
        row.last_error = f"menu re-sync failed: {_safe(exc)}"  # the old key and prompt still work
        row.updated_at = now
        await session.flush()
        return row
    row.key_hash = key_hash
    row.last_error = None
    row.updated_at = now
    await session.flush()
    return row
