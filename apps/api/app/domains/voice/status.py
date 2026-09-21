"""What an owner or an admin is shown about voice ordering, worked out once in Python so no
client re-implements the rules (CLAUDE.md §2). The owner gets plain words; the internal error
detail is for the admin only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.state import VOICE_IN_FLIGHT, VoiceState
from app.domains.voice.models import VoiceAgent
from app.domains.voice.provisioning import STEPS, safe_message

Phase = Literal["unavailable", "off", "setting_up", "active", "failed", "turning_off"]
StepState = Literal["done", "running", "pending", "failed"]

# What the owner reads, grouped so the list stays short.
_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("checking", "Checking your restaurant", ("checking",)),
    ("number", "Assigning a phone number", ("number",)),
    ("agent", "Creating the voice agent", ("agent",)),
    ("configure", "Connecting it to your orders", ("configure",)),
    ("line", "Connecting the phone line", ("link", "route")),
    ("verify", "Verifying the setup", ("verify",)),
)
assert {s for _, _, steps in _GROUPS for s in steps} == set(STEPS)


@dataclass(frozen=True)
class StepView:
    key: str
    label: str
    state: StepState


@dataclass(frozen=True)
class VoiceView:
    allowed: bool
    phase: Phase
    status: str  # the state machine value, or "off" when there is no row
    steps: list[StepView]
    phone_number: str | None
    message: str | None  # plain words for the owner
    detail: str | None  # internal; admin only
    can_enable: bool
    can_disable: bool
    updated_at: datetime | None


def _steps(row: VoiceAgent) -> list[StepView]:
    state = VoiceState(row.status)
    done = set(row.completed_steps)
    live = state in (VoiceState.ENABLE_REQUESTED, VoiceState.PROVISIONING)
    failed = state == VoiceState.PROVISIONING_FAILED
    views: list[StepView] = []
    running_given = False
    for key, label, members in _GROUPS:
        if all(m in done for m in members):
            step_state: StepState = "done"
        elif failed and row.failed_step in members:
            step_state = "failed"
        elif live and not running_given:
            step_state, running_given = "running", True
        else:
            step_state = "pending"
        views.append(StepView(key, label, step_state))
    return views


def build_view(row: VoiceAgent | None, allowed: bool, restaurant_active: bool) -> VoiceView:
    if row is None:
        can = allowed and restaurant_active
        return VoiceView(
            allowed=allowed,
            phase="off" if allowed else "unavailable",
            status="off",
            steps=[],
            phone_number=None,
            message=None,
            detail=None,
            can_enable=can,
            can_disable=False,
            updated_at=None,
        )
    state = VoiceState(row.status)
    phase: Phase
    if state == VoiceState.ACTIVE:
        phase = "active"
    elif state in (VoiceState.ENABLE_REQUESTED, VoiceState.PROVISIONING):
        phase = "setting_up"
    elif state in (VoiceState.DISABLE_REQUESTED, VoiceState.DEPROVISIONING):
        phase = "turning_off"
    elif state in (VoiceState.PROVISIONING_FAILED, VoiceState.DEPROVISIONING_FAILED):
        phase = "failed"
    else:
        phase = "off" if allowed else "unavailable"
    startable = state in (VoiceState.DISABLED, VoiceState.PROVISIONING_FAILED)
    return VoiceView(
        allowed=allowed,
        phase=phase,
        status=row.status,
        steps=_steps(row) if state in (*VOICE_IN_FLIGHT, VoiceState.PROVISIONING_FAILED) else [],
        phone_number=row.phone_number if "number" in row.completed_steps else None,
        message=safe_message(row.status, row.failed_step, row.last_error),
        detail=row.last_error,
        can_enable=allowed and restaurant_active and startable,
        can_disable=state
        in (
            VoiceState.ACTIVE,
            VoiceState.ENABLE_REQUESTED,
            VoiceState.PROVISIONING,
            VoiceState.PROVISIONING_FAILED,
            VoiceState.DEPROVISIONING_FAILED,
        ),
        updated_at=row.updated_at,
    )
