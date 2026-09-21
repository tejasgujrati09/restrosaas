"""Switching a restaurant's phone ordering agent on and off (docs/DECISIONS.md "Voice
provisioning"). Talks to the voice platform only through `VoicePlatform`.

Two halves. The **request** functions run inside an API request: they check the state machine,
record what was asked and by whom, and commit `enable_requested` / `disable_requested`; the job
is queued after the commit. The **job** functions (`run_enable`, `run_disable`) run in the worker
and do the slow platform calls one step at a time.

Idempotent by construction:
  * a row per outlet (unique), taken with `ON CONFLICT DO NOTHING` then locked, so two enable
    clicks make one row and one job;
  * a job claims its row with a conditional update, so a duplicate message does nothing;
  * every step records itself in `completed_steps` in its own transaction, so a retry resumes;
  * before creating anything on the platform the job looks for it (agent by its exact name, the
    number's current link), so a call whose response was lost is found, not repeated;
  * a phone number is reserved for one agent by a unique index, so two restaurants cannot take
    the same one.

The agent is created and configured inactive, the number is linked and routed, the setup is
verified against the platform, and only then is the agent switched on. Calls can never reach a
half-built agent. A phone number that is already linked to an agent is never taken.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.core.state import VOICE_IN_FLIGHT, VoiceState, transition_voice
from app.db.session import tenant_session
from app.domains.staff.models import AuditLog
from app.domains.tenant.models import Restaurant
from app.domains.voice.auth import new_voice_key
from app.domains.voice.jobs import JobKind, enqueue
from app.domains.voice.menu_source import load_prompt_menu
from app.domains.voice.models import VoiceAgent, VoiceProvisioningAttempt
from app.domains.voice.platform import (
    AgentSpec,
    PhoneNumber,
    VoicePlatform,
    VoicePlatformError,
)
from app.domains.voice.prompt import PromptMenu, build_agent_prompt
from app.domains.voice.tools import CALLER_VARIABLE, build_tools
from app.errors import ApiError
from app.realtime.hooks import after_commit

logger = structlog.get_logger()

# The order the job runs its steps in. `completed_steps` holds the ones that have succeeded.
STEPS = ("checking", "number", "agent", "configure", "link", "route", "verify")
# Kept when the owner switches back on: the agent, its number and the routing still exist.
_KEPT_ON_REENABLE = ("number", "agent", "link", "route")

LEASE = timedelta(seconds=120)  # a job that has not touched its row for this long is presumed dead
REQUEST_STALE = timedelta(seconds=30)  # a requested job nobody has claimed by now is queued again
DRAIN = timedelta(minutes=10)  # how long a call already in progress may still place its order


class JobOutcome(StrEnum):
    DONE = "done"
    SKIPPED = "skipped"  # nothing to do: already handled, or not this job's state
    RETRY = "retry"  # a transient platform error: queue again after a delay
    FAILED = "failed"
    SUPERSEDED = "superseded"  # the owner or an admin asked to turn it off meanwhile


class StepFailed(Exception):
    """A step could not finish. `code` says why in a stable word; `detail` is internal."""

    def __init__(self, step: str, code: str, detail: str, *, retryable: bool = False) -> None:
        self.step = step
        self.code = code
        self.detail = detail
        self.retryable = retryable
        super().__init__(f"{step}: {code}: {detail}")


# What the owner is told. Never the platform's own words.
_ADMIN = "Please contact your administrator."
_CODE_MESSAGES = {
    "menu_empty": "Add at least one available menu item, then try again.",
    "restaurant_suspended": "This restaurant is suspended, so voice ordering cannot be set up.",
    "not_allowed": f"Voice ordering is not available for this restaurant. {_ADMIN}",
    "no_number_available": f"No phone number is available right now. {_ADMIN}",
    "number_unavailable": f"Its phone number is not available. {_ADMIN}",
    "number_in_use": f"Its phone number is already in use. {_ADMIN}",
}
_STEP_MESSAGES = {
    "checking": "We couldn't check that your restaurant is ready.",
    "number": "We couldn't assign a phone number.",
    "agent": "We couldn't create the voice agent.",
    "configure": "We couldn't connect the voice agent to your orders.",
    "link": "We couldn't connect the phone number.",
    "route": "We couldn't connect the phone number.",
    "verify": "We couldn't verify the setup.",
}


def safe_message(status: str, failed_step: str | None, error: str | None) -> str | None:
    """A plain sentence for the owner, or None when nothing is wrong."""
    if status == VoiceState.PROVISIONING_FAILED:
        code = (error or "").split(":", 1)[0]
        return _CODE_MESSAGES.get(code) or _STEP_MESSAGES.get(
            failed_step or "", "We couldn't finish setting up voice ordering."
        )
    if status == VoiceState.DEPROVISIONING_FAILED:
        return "We couldn't finish turning voice ordering off. Please try again."
    return None


# ---------------------------------------------------------------------------------------------
# Request side


def _audit(
    session: AsyncSession,
    row: VoiceAgent,
    action: str,
    actor: UUID | None,
    before: str | None,
    extra: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor,
            restaurant_id=row.restaurant_id,
            action=action,
            target_type="voice_agent",
            target_id=row.id,
            before={"status": before} if before else None,
            after={"status": row.status, **(extra or {})},
        )
    )


def _set_state(row: VoiceAgent, target: VoiceState, now: datetime) -> str:
    before = row.status
    row.status = transition_voice(VoiceState(before), target)
    row.updated_at = now
    return before


async def get_voice_agent(
    session: AsyncSession, outlet_id: UUID, *, lock: bool = False
) -> VoiceAgent | None:
    stmt = select(VoiceAgent).where(VoiceAgent.outlet_id == outlet_id)
    if lock:
        stmt = stmt.with_for_update()
    row: VoiceAgent | None = await session.scalar(stmt)
    return row


def _open_attempt(
    session: AsyncSession,
    row: VoiceAgent,
    kind: JobKind,
    actor: UUID | None,
    by_platform_admin: bool,
    now: datetime,
) -> None:
    session.add(
        VoiceProvisioningAttempt(
            restaurant_id=row.restaurant_id,
            voice_agent_id=row.id,
            kind=kind,
            requested_by=actor,
            requested_by_platform_admin=by_platform_admin,
            started_at=now,
        )
    )


async def _close_open_attempts(
    session: AsyncSession,
    row_id: UUID,
    kind: JobKind | None,
    outcome: str,
    now: datetime,
    *,
    failed_step: str | None = None,
    error: str | None = None,
) -> None:
    stmt = (
        update(VoiceProvisioningAttempt)
        .where(
            VoiceProvisioningAttempt.voice_agent_id == row_id,
            VoiceProvisioningAttempt.finished_at.is_(None),
        )
        .values(finished_at=now, outcome=outcome, failed_step=failed_step, error=error)
    )
    if kind is not None:
        stmt = stmt.where(VoiceProvisioningAttempt.kind == kind)
    await session.execute(stmt)


def _queue(session: AsyncSession, kind: JobKind, row: VoiceAgent) -> None:
    restaurant_id, outlet_id = row.restaurant_id, row.outlet_id

    async def go() -> None:
        enqueue(kind, restaurant_id, outlet_id)

    after_commit(session, go)


async def request_enable(
    session: AsyncSession,
    *,
    restaurant_id: UUID,
    outlet_id: UUID,
    actor: UUID,
    by_platform_admin: bool,
    now: datetime,
) -> VoiceAgent:
    """Asks for voice ordering to be set up. Safe to repeat: asking while it is already being
    set up, or is on, changes nothing and queues nothing. Starting again from a failure keeps
    the steps that already succeeded."""
    _, key_hash = new_voice_key(restaurant_id)  # a placeholder no one holds until `configure`
    inserted = await session.execute(
        insert(VoiceAgent)
        .values(
            restaurant_id=restaurant_id,
            outlet_id=outlet_id,
            status=VoiceState.ENABLE_REQUESTED,
            key_hash=key_hash,
            enabled_by=actor,
            completed_steps=[],
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[VoiceAgent.outlet_id])
        .returning(VoiceAgent.id)
    )
    fresh = inserted.scalar_one_or_none() is not None
    row = await get_voice_agent(session, outlet_id, lock=True)
    assert row is not None
    state = VoiceState(row.status)

    if fresh:
        _open_attempt(session, row, "enable", actor, by_platform_admin, now)
        _audit(session, row, "voice.enable_requested", actor, None)
        _queue(session, "enable", row)
        return row

    if state in (VoiceState.ENABLE_REQUESTED, VoiceState.PROVISIONING, VoiceState.ACTIVE):
        return row  # a repeat click, a second tab, a retried request
    if state in (VoiceState.DISABLE_REQUESTED, VoiceState.DEPROVISIONING):
        raise ApiError(
            409, "voice_turning_off", "Voice ordering is being turned off. Try again in a moment."
        )
    if state == VoiceState.DEPROVISIONING_FAILED:
        raise ApiError(
            409,
            "voice_turning_off",
            "Voice ordering could not be turned off yet. Finish turning it off first.",
        )

    # disabled or provisioning_failed
    before = _set_state(row, VoiceState.ENABLE_REQUESTED, now)
    if state == VoiceState.DISABLED:
        row.completed_steps = [s for s in row.completed_steps if s in _KEPT_ON_REENABLE]
    row.last_error = None
    row.failed_step = None
    row.drain_until = None  # a call from before the disable no longer counts
    row.enabled_by = actor
    _open_attempt(session, row, "enable", actor, by_platform_admin, now)
    _audit(session, row, "voice.enable_requested", actor, before)
    _queue(session, "enable", row)
    return row


async def request_disable(
    session: AsyncSession,
    row: VoiceAgent,
    *,
    actor: UUID,
    by_platform_admin: bool,
    now: datetime,
    reason: str | None = None,
) -> VoiceAgent:
    """Asks for voice ordering to be turned off. New calls stop; a call already in progress
    can still place its order for `DRAIN`. Nothing is deleted, so it can be turned back on."""
    state = VoiceState(row.status)
    if state in (VoiceState.DISABLE_REQUESTED, VoiceState.DEPROVISIONING, VoiceState.DISABLED):
        return row
    was_live = state in (VoiceState.ACTIVE, VoiceState.DEPROVISIONING_FAILED)
    before = _set_state(row, VoiceState.DISABLE_REQUESTED, now)
    await _close_open_attempts(session, row.id, "enable", "superseded", now)
    if was_live and row.drain_until is None:
        row.drain_until = now + DRAIN
    row.disabled_by = actor
    _open_attempt(session, row, "disable", actor, by_platform_admin, now)
    _audit(
        session,
        row,
        "voice.disable_requested",
        actor,
        before,
        {"by": "platform_admin" if by_platform_admin else "owner", "reason": reason},
    )
    _queue(session, "disable", row)
    return row


def stale_request(row: VoiceAgent, now: datetime) -> JobKind | None:
    """The job a status read should queue again: a request nobody claimed (the queue lost the
    message) or a job that stopped touching its row (its worker died)."""
    state = VoiceState(row.status)
    age = now - row.updated_at
    if state == VoiceState.ENABLE_REQUESTED and age > REQUEST_STALE:
        return "enable"
    if state == VoiceState.PROVISIONING and age > LEASE:
        return "enable"
    if state == VoiceState.DISABLE_REQUESTED and age > REQUEST_STALE:
        return "disable"
    if state == VoiceState.DEPROVISIONING and age > LEASE:
        return "disable"
    return None


def in_flight(row: VoiceAgent) -> bool:
    return VoiceState(row.status) in VOICE_IN_FLIGHT


# ---------------------------------------------------------------------------------------------
# Platform specs


def agent_name(menu: PromptMenu, outlet_id: UUID) -> str:
    """Deterministic, so an agent whose creation response was lost can be found again."""
    return f"{menu.restaurant_name} phone orders [{outlet_id.hex[:8]}]"[:120]


def _spec(
    name: str, menu: PromptMenu, base_url: str | None, key: str | None, *, active: bool
) -> AgentSpec:
    prompt, first_message = build_agent_prompt(menu)
    tools = build_tools(base_url, key) if base_url and key else ()
    return AgentSpec(
        name=name,
        description="Phone ordering agent (managed by the restaurant platform).",
        system_prompt=prompt,
        first_message=first_message,
        tools=tools,
        call_variables=(CALLER_VARIABLE,),
        active=active,
    )


def _digits(number: str) -> str:
    return "".join(c for c in number if c.isdigit())


def number_candidates(numbers: list[PhoneNumber], preferred: str | None) -> list[PhoneNumber]:
    """The numbers this restaurant may take, best first. A linked number is never among them.
    A configured number must exist and be free, or nothing is chosen."""
    if preferred:
        match = next((n for n in numbers if _digits(n.number) == _digits(preferred)), None)
        if match is None:
            raise StepFailed("number", "number_unavailable", "configured number not on the account")
        if match.linked_agent_id is not None:
            raise StepFailed("number", "number_in_use", "configured number is linked to an agent")
        return [match]
    free = [n for n in numbers if n.linked_agent_id is None]
    if not free:
        raise StepFailed("number", "no_number_available", "no unlinked number on the account")
    return free


# ---------------------------------------------------------------------------------------------
# Job side


@dataclass
class _Snap:
    row_id: UUID
    status: str
    completed: list[str]
    agent_id: str | None
    plan_id: int | None
    phone_number: str | None
    restaurant_status: str
    allowed: bool
    menu: PromptMenu


async def _snapshot(restaurant_id: UUID, outlet_id: UUID) -> _Snap | None:
    async with tenant_session(restaurant_id) as session:
        row = await get_voice_agent(session, outlet_id)
        restaurant = await session.get(Restaurant, restaurant_id)
        if row is None or restaurant is None:
            return None
        return _Snap(
            row_id=row.id,
            status=row.status,
            completed=list(row.completed_steps),
            agent_id=row.gupshup_agent_id,
            plan_id=row.sr_plan_id,
            phone_number=row.phone_number,
            restaurant_status=restaurant.status,
            allowed=restaurant.voice_orders_allowed,
            menu=await load_prompt_menu(session, restaurant_id, outlet_id),
        )


async def _record(
    restaurant_id: UUID,
    outlet_id: UUID,
    step: str | None,
    fields: dict[str, object],
    now: datetime,
    *,
    drop_steps: tuple[str, ...] = (),
) -> bool:
    """Writes a step's result. Always written (a created agent must be remembered even if the
    owner has since asked to turn it off); returns whether the job should carry on."""
    async with tenant_session(restaurant_id) as session:
        row = await get_voice_agent(session, outlet_id, lock=True)
        assert row is not None
        for name, value in fields.items():
            setattr(row, name, value)
        steps = [s for s in row.completed_steps if s not in drop_steps]
        if step and step not in steps:
            steps.append(step)
        row.completed_steps = steps
        row.updated_at = now  # the lease heartbeat
        return row.status == VoiceState.PROVISIONING


async def _claim(
    restaurant_id: UUID,
    outlet_id: UUID,
    wanted: VoiceState,
    working: VoiceState,
    now: datetime,
) -> UUID | None:
    async with tenant_session(restaurant_id) as session:
        row = await get_voice_agent(session, outlet_id, lock=True)
        if row is None:
            return None
        stale = row.status == working and now - row.updated_at > LEASE
        if row.status != wanted and not stale:
            return None
        if row.status == wanted:
            _set_state(row, working, now)
        else:
            row.updated_at = now
        return row.id


async def run_enable(
    platform: VoicePlatform,
    *,
    restaurant_id: UUID,
    outlet_id: UUID,
    tools_base_url: str,
    preferred_number: str | None,
    final: bool = False,
) -> JobOutcome:
    """The provisioning job. `final` means no more retries are coming, so a transient error
    now ends in `provisioning_failed` instead of asking to be queued again."""
    now = clock.utcnow()
    row_id = await _claim(
        restaurant_id, outlet_id, VoiceState.ENABLE_REQUESTED, VoiceState.PROVISIONING, now
    )
    if row_id is None:
        return JobOutcome.SKIPPED
    log = logger.bind(restaurant_id=str(restaurant_id), outlet_id=str(outlet_id))
    step = "checking"
    try:
        for step in STEPS:
            snap = await _snapshot(restaurant_id, outlet_id)
            if snap is None or snap.status != VoiceState.PROVISIONING:
                return await _superseded(restaurant_id, outlet_id, row_id)
            if step in snap.completed:
                continue
            log.info("voice_step", step=step)
            carry_on = await _STEP_FUNCS[step](
                platform, restaurant_id, outlet_id, snap, tools_base_url, preferred_number
            )
            if not carry_on:
                if step == "verify" and snap.agent_id:
                    # Turned off while it was being switched on: undo the switch-on, or the
                    # disable job's own switch-off could have landed first and been overridden.
                    with contextlib.suppress(VoicePlatformError):
                        await platform.set_agent_active(snap.agent_id, False)
                return await _superseded(restaurant_id, outlet_id, row_id)
    except StepFailed as exc:
        return await _fail_enable(restaurant_id, outlet_id, row_id, exc, final)
    except VoicePlatformError as exc:
        wrapped = StepFailed(
            step, "platform_error", f"{exc.op} failed (HTTP {exc.status})", retryable=exc.retryable
        )
        return await _fail_enable(restaurant_id, outlet_id, row_id, wrapped, final)

    now = clock.utcnow()
    async with tenant_session(restaurant_id) as session:
        row = await get_voice_agent(session, outlet_id, lock=True)
        assert row is not None
        if row.status != VoiceState.PROVISIONING:
            return await _superseded(restaurant_id, outlet_id, row_id)
        before = _set_state(row, VoiceState.ACTIVE, now)
        row.enabled_at = now
        row.last_error = None
        row.failed_step = None
        row.drain_until = None
        await _close_open_attempts(session, row.id, "enable", "succeeded", now)
        _audit(
            session, row, "voice.provisioned", row.enabled_by, before, {"number": row.phone_number}
        )
    log.info("voice_provisioned")
    return JobOutcome.DONE


async def _superseded(restaurant_id: UUID, outlet_id: UUID, row_id: UUID) -> JobOutcome:
    """The owner or an admin turned it off while we were working. The disable job takes over;
    what this job already created is recorded on the row for it to switch off."""
    logger.info("voice_enable_superseded", outlet_id=str(outlet_id))
    return JobOutcome.SUPERSEDED


async def _fail_enable(
    restaurant_id: UUID, outlet_id: UUID, row_id: UUID, exc: StepFailed, final: bool
) -> JobOutcome:
    now = clock.utcnow()
    detail = f"{exc.code}: {exc.detail}"
    retry = exc.retryable and not final
    logger.warning(
        "voice_provisioning_failed",
        outlet_id=str(outlet_id),
        step=exc.step,
        code=exc.code,
        retry=retry,
    )
    async with tenant_session(restaurant_id) as session:
        row = await get_voice_agent(session, outlet_id, lock=True)
        assert row is not None
        if row.status != VoiceState.PROVISIONING:
            return JobOutcome.SUPERSEDED
        if retry:
            _set_state(row, VoiceState.ENABLE_REQUESTED, now)
            row.last_error = detail
            await session.execute(
                update(VoiceProvisioningAttempt)
                .where(
                    VoiceProvisioningAttempt.voice_agent_id == row.id,
                    VoiceProvisioningAttempt.finished_at.is_(None),
                )
                .values(error=detail, failed_step=exc.step)
            )
            return JobOutcome.RETRY
        before = _set_state(row, VoiceState.PROVISIONING_FAILED, now)
        row.failed_step = exc.step
        row.last_error = detail
        await _close_open_attempts(
            session, row.id, "enable", "failed", now, failed_step=exc.step, error=detail
        )
        _audit(
            session, row, "voice.provisioning_failed", row.enabled_by, before, {"step": exc.step}
        )
    return JobOutcome.FAILED


# Each step returns whether the job should carry on (False: it was turned off meanwhile).
async def _step_checking(
    platform: VoicePlatform,
    restaurant_id: UUID,
    outlet_id: UUID,
    snap: _Snap,
    tools_base_url: str,
    preferred: str | None,
) -> bool:
    if snap.restaurant_status != "active":
        raise StepFailed("checking", "restaurant_suspended", snap.restaurant_status)
    if not snap.allowed:
        raise StepFailed("checking", "not_allowed", "admin has not allowed voice orders")
    if snap.menu.item_count == 0:
        raise StepFailed("checking", "menu_empty", "no orderable item")
    return await _record(restaurant_id, outlet_id, "checking", {}, clock.utcnow())


async def _step_number(
    platform: VoicePlatform,
    restaurant_id: UUID,
    outlet_id: UUID,
    snap: _Snap,
    tools_base_url: str,
    preferred: str | None,
) -> bool:
    numbers = await platform.list_numbers()
    if snap.plan_id is not None:  # reserved by an earlier attempt: it must still be ours to use
        mine = next((n for n in numbers if n.plan_id == snap.plan_id), None)
        if mine is None or mine.linked_agent_id not in (None, snap.agent_id):
            raise StepFailed("number", "number_unavailable", "the reserved number changed")
        return await _record(restaurant_id, outlet_id, "number", {}, clock.utcnow())

    for candidate in number_candidates(numbers, preferred):
        try:
            async with tenant_session(restaurant_id) as session:
                row = await get_voice_agent(session, outlet_id, lock=True)
                assert row is not None
                row.sr_plan_id = candidate.plan_id
                row.phone_number = candidate.number
                if "number" not in row.completed_steps:
                    row.completed_steps = [*row.completed_steps, "number"]
                row.updated_at = clock.utcnow()
                await session.flush()  # the unique index on sr_plan_id decides here
                return row.status == VoiceState.PROVISIONING
        except IntegrityError:
            continue  # another restaurant reserved it first; take the next one
    raise StepFailed("number", "no_number_available", "every free number was just taken")


async def _step_agent(
    platform: VoicePlatform,
    restaurant_id: UUID,
    outlet_id: UUID,
    snap: _Snap,
    tools_base_url: str,
    preferred: str | None,
) -> bool:
    name = agent_name(snap.menu, outlet_id)
    if snap.agent_id and await platform.agent_is_active(snap.agent_id) is not None:
        return await _record(restaurant_id, outlet_id, "agent", {}, clock.utcnow())
    agent_id = await platform.find_agent_by_name(name)  # a create whose answer was lost
    if agent_id is None:
        # Inactive and without tools: no key has been given out and no call can reach it.
        agent_id = await platform.create_agent(_spec(name, snap.menu, None, None, active=False))
    return await _record(
        restaurant_id,
        outlet_id,
        "agent",
        {"gupshup_agent_id": agent_id},
        clock.utcnow(),
        drop_steps=("configure", "link", "route", "verify") if agent_id != snap.agent_id else (),
    )


async def _step_configure(
    platform: VoicePlatform,
    restaurant_id: UUID,
    outlet_id: UUID,
    snap: _Snap,
    tools_base_url: str,
    preferred: str | None,
) -> bool:
    assert snap.agent_id is not None
    key, key_hash = new_voice_key(restaurant_id)
    name = agent_name(snap.menu, outlet_id)
    await platform.update_agent(
        snap.agent_id, _spec(name, snap.menu, tools_base_url, key, active=False)
    )
    return await _record(
        restaurant_id, outlet_id, "configure", {"key_hash": key_hash}, clock.utcnow()
    )


async def _step_link(
    platform: VoicePlatform,
    restaurant_id: UUID,
    outlet_id: UUID,
    snap: _Snap,
    tools_base_url: str,
    preferred: str | None,
) -> bool:
    assert snap.agent_id is not None and snap.plan_id is not None and snap.phone_number
    numbers = await platform.list_numbers()
    current = next((n for n in numbers if n.plan_id == snap.plan_id), None)
    if current is None:
        raise StepFailed("link", "number_unavailable", "the reserved number is gone")
    if current.linked_agent_id not in (None, snap.agent_id):
        raise StepFailed("link", "number_in_use", "the number was linked to another agent")
    if current.linked_agent_id is None:
        await platform.link_number(
            snap.plan_id, snap.agent_id, agent_name(snap.menu, outlet_id), snap.phone_number
        )
    return await _record(restaurant_id, outlet_id, "link", {}, clock.utcnow())


async def _step_route(
    platform: VoicePlatform,
    restaurant_id: UUID,
    outlet_id: UUID,
    snap: _Snap,
    tools_base_url: str,
    preferred: str | None,
) -> bool:
    assert snap.agent_id is not None and snap.plan_id is not None and snap.phone_number
    await platform.pass_caller_to_agent(snap.plan_id, snap.agent_id, snap.phone_number)
    return await _record(restaurant_id, outlet_id, "route", {}, clock.utcnow())


async def _step_verify(
    platform: VoicePlatform,
    restaurant_id: UUID,
    outlet_id: UUID,
    snap: _Snap,
    tools_base_url: str,
    preferred: str | None,
) -> bool:
    """Confirms against the platform, not our own bookkeeping, before the agent goes live:
    the agent exists, the number points at it, and after switching it on it reports active."""
    assert snap.agent_id is not None and snap.plan_id is not None
    if await platform.agent_is_active(snap.agent_id) is None:
        raise StepFailed("verify", "agent_missing", "agent not found on the platform")
    numbers = await platform.list_numbers()
    linked = next((n for n in numbers if n.plan_id == snap.plan_id), None)
    if linked is None or linked.linked_agent_id != snap.agent_id:
        raise StepFailed("verify", "routing_missing", "number does not point at the agent")
    await platform.set_agent_active(snap.agent_id, True)
    if await platform.agent_is_active(snap.agent_id) is not True:
        raise StepFailed("verify", "agent_inactive", "agent did not become active", retryable=True)
    return await _record(restaurant_id, outlet_id, "verify", {}, clock.utcnow())


_STEP_FUNCS = {
    "checking": _step_checking,
    "number": _step_number,
    "agent": _step_agent,
    "configure": _step_configure,
    "link": _step_link,
    "route": _step_route,
    "verify": _step_verify,
}


async def run_disable(
    platform: VoicePlatform, *, restaurant_id: UUID, outlet_id: UUID, final: bool = False
) -> JobOutcome:
    """Stops the agent answering. The agent, the number and the routing are kept so it can be
    switched back on; order history is untouched. Tools keep working until `drain_until`, so a
    caller already on the line can finish their order."""
    now = clock.utcnow()
    row_id = await _claim(
        restaurant_id, outlet_id, VoiceState.DISABLE_REQUESTED, VoiceState.DEPROVISIONING, now
    )
    if row_id is None:
        return JobOutcome.SKIPPED
    snap = await _snapshot_row(restaurant_id, outlet_id)
    error: str | None = None
    retryable = False
    if snap is not None and snap.agent_id:
        try:
            await platform.set_agent_active(snap.agent_id, False)
        except VoicePlatformError as exc:
            if exc.status != 404:  # an agent that is already gone is already off
                error = f"platform_error: {exc.op} failed (HTTP {exc.status})"
                retryable = exc.retryable
    now = clock.utcnow()
    async with tenant_session(restaurant_id) as session:
        row = await get_voice_agent(session, outlet_id, lock=True)
        assert row is not None
        if error is None:
            before = _set_state(row, VoiceState.DISABLED, now)
            row.disabled_at = now
            row.last_error = None
            row.failed_step = None
            await _close_open_attempts(session, row.id, "disable", "succeeded", now)
            _audit(session, row, "voice.disabled", row.disabled_by, before)
            return JobOutcome.DONE
        if retryable and not final:
            _set_state(row, VoiceState.DISABLE_REQUESTED, now)
            row.last_error = error
            return JobOutcome.RETRY
        before = _set_state(row, VoiceState.DEPROVISIONING_FAILED, now)
        row.last_error = error
        await _close_open_attempts(session, row.id, "disable", "failed", now, error=error)
        _audit(session, row, "voice.deprovisioning_failed", row.disabled_by, before)
        return JobOutcome.FAILED


@dataclass
class _RowSnap:
    agent_id: str | None


async def _snapshot_row(restaurant_id: UUID, outlet_id: UUID) -> _RowSnap | None:
    async with tenant_session(restaurant_id) as session:
        row = await get_voice_agent(session, outlet_id)
        return _RowSnap(row.gupshup_agent_id) if row else None


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
    if row.status != VoiceState.ACTIVE or not row.gupshup_agent_id:
        raise ApiError(409, "voice_not_active", "The voice agent is not on.")
    key, key_hash = new_voice_key(row.restaurant_id)
    try:
        await platform.update_agent(
            row.gupshup_agent_id,
            _spec(agent_name(menu, row.outlet_id), menu, tools_base_url, key, active=True),
        )
    except VoicePlatformError as exc:
        row.last_error = f"menu re-sync failed: {exc.op} (HTTP {exc.status})"
        row.updated_at = now  # the old key and prompt still work
        await session.flush()
        return row
    row.key_hash = key_hash
    row.last_error = None
    row.updated_at = now
    await session.flush()
    return row
