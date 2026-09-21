"""Platform admin API: the SaaS operator's view across restaurants.

A platform admin signs in with a phone OTP like staff, but gets a different token that only
these routes accept. Reads use `platform_session` (two SELECT-only policies, migration 0008).
Anything that *changes* a restaurant opens that restaurant's normal tenant session, so the
existing tenant RLS is what authorises the write. See docs/DECISIONS.md "Platform admin".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.common import ERRORS, invalid
from app.api.v1.voice_agent import VoiceStepOut
from app.auth import issue_platform_token, otp_store
from app.config import settings
from app.core.permissions import assert_is_platform_admin
from app.db.session import anonymous_session, tenant_session
from app.deps import PlatformContext, get_platform_context
from app.domains.staff.models import AppUser, AuditLog, PlatformAdmin
from app.domains.tenant.models import Outlet, Restaurant
from app.domains.voice import factory, provisioning
from app.domains.voice.models import VoiceAgent, VoiceProvisioningAttempt
from app.domains.voice.status import build_view
from app.errors import ApiError
from app.realtime.hooks import run_after_commit

router = APIRouter(prefix="/v1/platform", tags=["platform"])
logger = structlog.get_logger()

_PHONE_PATTERN = r"^\+[1-9][0-9]{7,14}$"

PlatformCtx = Annotated[PlatformContext, Depends(get_platform_context, scope="function")]


class PlatformOtpRequestIn(BaseModel):
    phone: str = Field(pattern=_PHONE_PATTERN)


class PlatformOtpVerifyIn(BaseModel):
    phone: str = Field(pattern=_PHONE_PATTERN)
    code: str = Field(min_length=6, max_length=6)


class PlatformTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


async def _admin_for_phone(phone: str) -> tuple[AppUser, PlatformAdmin] | None:
    async with anonymous_session() as session:
        row = (
            await session.execute(
                select(AppUser, PlatformAdmin)
                .join(PlatformAdmin, PlatformAdmin.user_id == AppUser.id)
                .where(AppUser.phone == phone, PlatformAdmin.active.is_(True))
            )
        ).first()
    return None if row is None else (row[0], row[1])


@router.post("/auth/otp/request", status_code=202)
async def request_platform_otp(body: PlatformOtpRequestIn) -> None:
    """Always 202, whether or not the phone is a platform admin, so it cannot be used to
    find out who the admins are."""
    otp_store.throttle(f"platform:{body.phone}")
    if await _admin_for_phone(body.phone) is None:
        return
    code = otp_store.issue(f"platform:{body.phone}")
    if settings.otp_dev_mode:
        print(f"[dev] platform OTP for {body.phone}: {code}", flush=True)  # noqa: T201
    else:
        logger.warning("otp_delivery_not_configured")


@router.post("/auth/otp/verify", responses=ERRORS)
async def verify_platform_otp(body: PlatformOtpVerifyIn) -> PlatformTokenOut:
    invalid_code = ApiError(401, "invalid_otp", "That code is not right. Try again.")
    if not otp_store.verify(f"platform:{body.phone}", body.code):
        raise invalid_code
    found = await _admin_for_phone(body.phone)
    if found is None:
        raise invalid_code
    user, admin = found
    async with anonymous_session() as session:
        stored = await session.get(AppUser, user.id)
        if stored is not None:
            stored.last_login_at = datetime.now(UTC)
    return PlatformTokenOut(access_token=issue_platform_token(user.id, admin.id))


class PlatformMeOut(BaseModel):
    user_id: UUID
    name: str | None
    phone: str


@router.get("/me", responses=ERRORS)
async def me(ctx: PlatformCtx) -> PlatformMeOut:
    assert_is_platform_admin(ctx.actor)
    user = await ctx.session.get(AppUser, ctx.actor.user_id)
    assert user is not None
    return PlatformMeOut(user_id=user.id, name=user.name, phone=user.phone)


class PlatformRestaurantOut(BaseModel):
    id: UUID
    brand_name: str
    legal_name: str
    gstin: str | None
    plan: str
    status: Literal["active", "suspended"]
    voice_orders_allowed: bool
    created_at: datetime


def _restaurant_out(r: Restaurant) -> PlatformRestaurantOut:
    return PlatformRestaurantOut(
        id=r.id,
        brand_name=r.brand_name,
        legal_name=r.legal_name,
        gstin=r.gstin,
        plan=r.subscription_plan,
        status="suspended" if r.status == "suspended" else "active",
        voice_orders_allowed=r.voice_orders_allowed,
        created_at=r.created_at,
    )


@router.get("/restaurants", responses=ERRORS)
async def list_restaurants(
    ctx: PlatformCtx,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: Literal["active", "suspended"] | None = None,
) -> list[PlatformRestaurantOut]:
    assert_is_platform_admin(ctx.actor)
    stmt = select(Restaurant).order_by(Restaurant.created_at.desc()).limit(500)
    if status is not None:
        stmt = stmt.where(Restaurant.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Restaurant.brand_name.ilike(like) | Restaurant.legal_name.ilike(like))
    return [_restaurant_out(r) for r in await ctx.session.scalars(stmt)]


class RestaurantStatusIn(BaseModel):
    status: Literal["active", "suspended"]
    reason: str | None = Field(default=None, max_length=300)


@router.put("/restaurants/{restaurant_id}/status", responses=ERRORS)
async def set_restaurant_status(
    restaurant_id: UUID, body: RestaurantStatusIn, ctx: PlatformCtx
) -> PlatformRestaurantOut:
    """Suspend or reactivate. Suspending needs a reason. Setting the status a restaurant
    already has is a no-op that writes no audit row, which is why this takes no
    Idempotency-Key: repeating it cannot do anything twice."""
    assert_is_platform_admin(ctx.actor)
    reason = (body.reason or "").strip()
    if body.status == "suspended" and len(reason) < 3:
        raise invalid("reason", "Say why you are suspending this restaurant.")
    # The write goes through the restaurant's own tenant session, so the existing tenant
    # policy on `restaurant` and `audit_log` is what allows it.
    async with tenant_session(restaurant_id) as session:
        restaurant = await session.get(Restaurant, restaurant_id)
        if restaurant is None:
            raise ApiError(404, "restaurant_not_found", "That restaurant does not exist.")
        if restaurant.status != body.status:
            before = restaurant.status
            restaurant.status = body.status
            session.add(
                AuditLog(
                    actor_user_id=ctx.actor.user_id,
                    restaurant_id=restaurant_id,
                    action=(
                        "restaurant.suspended"
                        if body.status == "suspended"
                        else "restaurant.reactivated"
                    ),
                    target_type="restaurant",
                    target_id=restaurant_id,
                    before={"status": before},
                    after={"status": body.status, "reason": reason or None},
                )
            )
        return _restaurant_out(restaurant)


class AuditEntryOut(BaseModel):
    id: UUID
    at: datetime
    action: str
    actor_name: str | None
    actor_phone: str | None
    restaurant_id: UUID | None
    restaurant_name: str | None
    target_type: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@router.get("/audit-log", responses=ERRORS)
async def audit_log(
    ctx: PlatformCtx,
    restaurant_id: UUID | None = None,
    action_prefix: Annotated[str | None, Query(max_length=60)] = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AuditEntryOut]:
    """Newest first. Pass the last row's `at` as `before` for the next page.
    `action_prefix=restaurant.` shows only what the platform did to restaurants."""
    assert_is_platform_admin(ctx.actor)
    stmt = (
        select(AuditLog, AppUser.name, AppUser.phone, Restaurant.brand_name)
        .join(AppUser, AppUser.id == AuditLog.actor_user_id, isouter=True)
        .join(Restaurant, Restaurant.id == AuditLog.restaurant_id, isouter=True)
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    if restaurant_id is not None:
        stmt = stmt.where(AuditLog.restaurant_id == restaurant_id)
    if action_prefix:
        stmt = stmt.where(AuditLog.action.startswith(action_prefix, autoescape=True))
    if before is not None:
        stmt = stmt.where(AuditLog.at < before)
    rows = (await ctx.session.execute(stmt)).all()
    return [
        AuditEntryOut(
            id=a.id,
            at=a.at,
            action=a.action,
            actor_name=name,
            actor_phone=phone,
            restaurant_id=a.restaurant_id,
            restaurant_name=brand,
            target_type=a.target_type,
            before=a.before,
            after=a.after,
        )
        for a, name, phone, brand in (r._tuple() for r in rows)
    ]


# ---------------------------------------------------------------------------------------------
# Voice ordering: the platform decides whether a restaurant may use it at all; the owner then
# switches it on (docs/DECISIONS.md "Voice provisioning").


class VoiceAllowedIn(BaseModel):
    allowed: bool
    reason: str | None = Field(default=None, max_length=300)


class VoiceAttemptOut(BaseModel):
    kind: Literal["enable", "disable"]
    started_at: datetime
    finished_at: datetime | None
    outcome: str | None
    failed_step: str | None
    error: str | None
    requested_by_platform_admin: bool


class VoiceOutletOut(BaseModel):
    outlet_id: UUID
    outlet_name: str
    status: str
    phase: str
    steps: list[VoiceStepOut]
    phone_number: str | None
    agent_id: str | None
    message: str | None
    detail: str | None  # internal error detail, for troubleshooting
    can_retry: bool
    updated_at: datetime | None
    attempts: list[VoiceAttemptOut]


class PlatformVoiceOut(BaseModel):
    restaurant_id: UUID
    allowed: bool
    outlets: list[VoiceOutletOut]


async def _voice_out(session: Any, restaurant: Restaurant) -> PlatformVoiceOut:
    outlets = (
        await session.scalars(
            select(Outlet).where(Outlet.restaurant_id == restaurant.id).order_by(Outlet.name)
        )
    ).all()
    rows = {
        r.outlet_id: r
        for r in await session.scalars(
            select(VoiceAgent).where(VoiceAgent.restaurant_id == restaurant.id)
        )
    }
    result: list[VoiceOutletOut] = []
    for outlet in outlets:
        row = rows.get(outlet.id)
        view = build_view(row, restaurant.voice_orders_allowed, restaurant.status == "active")
        attempts = (
            list(
                await session.scalars(
                    select(VoiceProvisioningAttempt)
                    .where(VoiceProvisioningAttempt.voice_agent_id == row.id)
                    .order_by(VoiceProvisioningAttempt.started_at.desc())
                    .limit(10)
                )
            )
            if row
            else []
        )
        result.append(
            VoiceOutletOut(
                outlet_id=outlet.id,
                outlet_name=outlet.name,
                status=view.status,
                phase=view.phase,
                steps=[VoiceStepOut(key=x.key, label=x.label, state=x.state) for x in view.steps],
                phone_number=view.phone_number,
                agent_id=row.gupshup_agent_id if row else None,
                message=view.message,
                detail=view.detail,
                can_retry=row is not None
                and restaurant.voice_orders_allowed
                and row.status in ("provisioning_failed", "deprovisioning_failed"),
                updated_at=view.updated_at,
                attempts=[
                    VoiceAttemptOut(
                        kind="enable" if a.kind == "enable" else "disable",
                        started_at=a.started_at,
                        finished_at=a.finished_at,
                        outcome=a.outcome,
                        failed_step=a.failed_step,
                        error=a.error,
                        requested_by_platform_admin=a.requested_by_platform_admin,
                    )
                    for a in attempts
                ],
            )
        )
    return PlatformVoiceOut(
        restaurant_id=restaurant.id, allowed=restaurant.voice_orders_allowed, outlets=result
    )


@router.get("/restaurants/{restaurant_id}/voice", responses=ERRORS)
async def get_restaurant_voice(restaurant_id: UUID, ctx: PlatformCtx) -> PlatformVoiceOut:
    assert_is_platform_admin(ctx.actor)
    async with tenant_session(restaurant_id) as session:
        restaurant = await session.get(Restaurant, restaurant_id)
        if restaurant is None:
            raise ApiError(404, "restaurant_not_found", "That restaurant does not exist.")
        return await _voice_out(session, restaurant)


@router.put("/restaurants/{restaurant_id}/voice-orders", responses=ERRORS)
async def set_voice_orders_allowed(
    restaurant_id: UUID, body: VoiceAllowedIn, ctx: PlatformCtx
) -> PlatformVoiceOut:
    """Allow or stop voice ordering for a restaurant. Stopping also turns off whatever the
    owner had switched on: the agent stops taking new calls and a call in progress can finish
    (the same ten-minute window as an owner's disable). Nothing is deleted. Repeating it
    changes nothing, so it takes no Idempotency-Key."""
    assert_is_platform_admin(ctx.actor)
    from app import clock

    async with tenant_session(restaurant_id) as session:
        restaurant = await session.get(Restaurant, restaurant_id)
        if restaurant is None:
            raise ApiError(404, "restaurant_not_found", "That restaurant does not exist.")
        if restaurant.voice_orders_allowed != body.allowed:
            restaurant.voice_orders_allowed = body.allowed
            session.add(
                AuditLog(
                    actor_user_id=ctx.actor.user_id,
                    restaurant_id=restaurant_id,
                    action="restaurant.voice_allowed"
                    if body.allowed
                    else "restaurant.voice_disallowed",
                    target_type="restaurant",
                    target_id=restaurant_id,
                    before={"voice_orders_allowed": not body.allowed},
                    after={"voice_orders_allowed": body.allowed, "reason": body.reason},
                )
            )
        if not body.allowed:
            for row in await session.scalars(
                select(VoiceAgent)
                .where(VoiceAgent.restaurant_id == restaurant_id)
                .with_for_update()
            ):
                await provisioning.request_disable(
                    session,
                    row,
                    actor=ctx.actor.user_id,
                    by_platform_admin=True,
                    now=clock.utcnow(),
                    reason="admin turned voice ordering off for this restaurant",
                )
        out = await _voice_out(session, restaurant)
    await run_after_commit(session)
    return out


@router.post(
    "/restaurants/{restaurant_id}/voice/{outlet_id}/retry", status_code=202, responses=ERRORS
)
async def retry_voice(restaurant_id: UUID, outlet_id: UUID, ctx: PlatformCtx) -> PlatformVoiceOut:
    """Try a failed setup (or a failed turn-off) again. Steps that already succeeded are kept."""
    assert_is_platform_admin(ctx.actor)
    from app import clock

    async with tenant_session(restaurant_id) as session:
        restaurant = await session.get(Restaurant, restaurant_id)
        if restaurant is None:
            raise ApiError(404, "restaurant_not_found", "That restaurant does not exist.")
        row = await provisioning.get_voice_agent(session, outlet_id, lock=True)
        if row is None or row.restaurant_id != restaurant_id:
            raise ApiError(404, "not_found", "That outlet has no voice setup.")
        if row.status == "provisioning_failed":
            if not restaurant.voice_orders_allowed:
                raise ApiError(
                    409, "voice_not_allowed", "Voice ordering is not allowed for this restaurant."
                )
            factory.tools_base_url()
            await provisioning.request_enable(
                session,
                restaurant_id=restaurant_id,
                outlet_id=outlet_id,
                actor=ctx.actor.user_id,
                by_platform_admin=True,
                now=clock.utcnow(),
            )
        elif row.status == "deprovisioning_failed":
            await provisioning.request_disable(
                session, row, actor=ctx.actor.user_id, by_platform_admin=True, now=clock.utcnow()
            )
        else:
            raise ApiError(409, "voice_not_failed", "There is nothing to retry.")
        out = await _voice_out(session, restaurant)
    await run_after_commit(session)
    return out
