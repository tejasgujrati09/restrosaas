from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.api.v1.common import ERRORS, Ctx, IdempotencyKeyHeader, idempotent_write, not_found
from app.audit import audit
from app.config import settings
from app.core.permissions import Capability, Role, assert_can
from app.deps import OutletContext
from app.domains.staff.models import AppUser, StaffInvite, StaffRole
from app.domains.tenant.models import Restaurant, Station
from app.errors import ApiError

router = APIRouter(prefix="/v1/outlets/{outlet_id}", tags=["staff"])

PHONE_PATTERN = r"^\+[1-9][0-9]{7,14}$"


class StaffOut(BaseModel):
    id: UUID
    user_id: UUID
    name: str | None
    phone: str
    role: Role
    active: bool


class StaffPatchIn(BaseModel):
    active: bool | None = None
    role: Role | None = None


class InviteIn(BaseModel):
    phone: str = Field(pattern=PHONE_PATTERN)
    role: Role
    station_id: UUID | None = None


class InviteOut(BaseModel):
    id: UUID
    phone: str
    role: Role
    expires_at: datetime
    # Only returned when the invite is created; the token is stored hashed.
    link: str | None
    whatsapp_url: str | None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _capability_for(role: Role) -> Capability:
    return Capability.MANAGE_WAITER_STAFF if role == Role.WAITER else Capability.MANAGE_ALL_STAFF


async def _staff_out(ctx: OutletContext, row: StaffRole) -> StaffOut:
    user = await ctx.session.get(AppUser, row.user_id)
    assert user is not None
    return StaffOut(
        id=row.id,
        user_id=row.user_id,
        name=user.name,
        phone=user.phone,
        role=Role(row.role),
        active=row.active,
    )


@router.get("/staff", responses=ERRORS)
async def list_staff(ctx: Ctx) -> list[StaffOut]:
    assert_can(ctx.actor, Capability.MANAGE_WAITER_STAFF, ctx.outlet_id)
    rows = await ctx.session.execute(
        select(StaffRole, AppUser)
        .join(AppUser, AppUser.id == StaffRole.user_id)
        .where(StaffRole.outlet_id == ctx.outlet_id)
        .order_by(StaffRole.role, AppUser.phone)
    )
    return [
        StaffOut(
            id=r.id,
            user_id=r.user_id,
            name=u.name,
            phone=u.phone,
            role=Role(r.role),
            active=r.active,
        )
        for r, u in rows
    ]


@router.patch("/staff/{staff_id}", responses=ERRORS)
async def update_staff(
    staff_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: StaffPatchIn
) -> StaffOut:
    assert_can(ctx.actor, Capability.MANAGE_WAITER_STAFF, ctx.outlet_id)

    async def produce() -> StaffOut:
        row = await ctx.session.get(StaffRole, staff_id)
        if row is None or row.outlet_id != ctx.outlet_id:
            raise not_found("Staff member")
        # Managers only manage waiters; everyone else, and every role change, is owner-only.
        assert_can(ctx.actor, _capability_for(Role(row.role)), ctx.outlet_id)
        if body.role is not None:
            assert_can(ctx.actor, Capability.MANAGE_ALL_STAFF, ctx.outlet_id)
        before = {"role": row.role, "active": row.active}
        new_role = body.role.value if body.role is not None else row.role
        new_active = body.active if body.active is not None else row.active
        if row.role == Role.OWNER and row.active and (not new_active or new_role != Role.OWNER):
            other_owners = await ctx.session.scalar(
                select(func.count())
                .select_from(StaffRole)
                .where(
                    StaffRole.outlet_id == ctx.outlet_id,
                    StaffRole.role == Role.OWNER.value,
                    StaffRole.active.is_(True),
                    StaffRole.id != row.id,
                )
            )
            if not other_owners:
                raise ApiError(409, "last_owner", "An outlet needs at least one active owner.")
        row.role, row.active = new_role, new_active
        await ctx.session.flush()
        audit(
            ctx,
            "staff.updated",
            "staff_role",
            row.id,
            before,
            {"role": row.role, "active": row.active},
        )
        return await _staff_out(ctx, row)

    return await idempotent_write(ctx, key, f"PATCH staff/{staff_id}", body, StaffOut, produce)


def _invite_out(invite: StaffInvite, token: str | None, brand: str | None) -> InviteOut:
    link = f"{settings.staff_base_url.rstrip('/')}/invite/{token}" if token else None
    whatsapp = None
    if link:
        text = quote(f"You're invited to join {brand} on RestoSaaS. Open this link: {link}")
        whatsapp = f"https://wa.me/{invite.phone.lstrip('+')}?text={text}"
    return InviteOut(
        id=invite.id,
        phone=invite.phone,
        role=Role(invite.role),
        expires_at=invite.expires_at,
        link=link,
        whatsapp_url=whatsapp,
    )


@router.get("/invites", responses=ERRORS)
async def list_invites(ctx: Ctx) -> list[InviteOut]:
    assert_can(ctx.actor, Capability.MANAGE_WAITER_STAFF, ctx.outlet_id)
    rows = await ctx.session.scalars(
        select(StaffInvite)
        .where(
            StaffInvite.outlet_id == ctx.outlet_id,
            StaffInvite.accepted_at.is_(None),
            StaffInvite.revoked_at.is_(None),
            StaffInvite.expires_at > datetime.now(UTC),
        )
        .order_by(StaffInvite.created_at.desc())
    )
    return [_invite_out(i, None, None) for i in rows]


@router.post("/invites", status_code=201, responses=ERRORS)
async def create_invite(ctx: Ctx, key: IdempotencyKeyHeader, body: InviteIn) -> InviteOut:
    assert_can(ctx.actor, _capability_for(body.role), ctx.outlet_id)

    async def produce() -> InviteOut:
        if body.station_id is not None:
            station = await ctx.session.get(Station, body.station_id)
            if station is None or station.outlet_id != ctx.outlet_id:
                raise not_found("Station")
        already = await ctx.session.scalar(
            select(func.count())
            .select_from(StaffRole)
            .join(AppUser, AppUser.id == StaffRole.user_id)
            .where(
                StaffRole.outlet_id == ctx.outlet_id,
                StaffRole.role == body.role.value,
                StaffRole.active.is_(True),
                AppUser.phone == body.phone,
            )
        )
        if already:
            raise ApiError(409, "already_staff", "That person already has this role here.")
        now = datetime.now(UTC)
        # A fresh invite replaces any still-pending one for the same person and role.
        await ctx.session.execute(
            update(StaffInvite)
            .where(
                StaffInvite.outlet_id == ctx.outlet_id,
                StaffInvite.phone == body.phone,
                StaffInvite.role == body.role.value,
                StaffInvite.accepted_at.is_(None),
                StaffInvite.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        token = secrets.token_urlsafe(32)
        invite = StaffInvite(
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            phone=body.phone,
            role=body.role.value,
            station_id=body.station_id,
            token_hash=hash_token(token),
            invited_by=ctx.actor.user_id,
            expires_at=now + timedelta(days=settings.invite_ttl_days),
        )
        ctx.session.add(invite)
        await ctx.session.flush()
        audit(
            ctx,
            "staff.invited",
            "staff_invite",
            invite.id,
            None,
            {"phone": body.phone, "role": body.role.value},
        )
        restaurant = await ctx.session.get(Restaurant, ctx.restaurant_id)
        assert restaurant is not None
        return _invite_out(invite, token, restaurant.brand_name)

    return await idempotent_write(ctx, key, "POST invites", body, InviteOut, produce)


@router.delete("/invites/{invite_id}", status_code=204, responses=ERRORS)
async def revoke_invite(invite_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> None:
    assert_can(ctx.actor, Capability.MANAGE_WAITER_STAFF, ctx.outlet_id)

    async def produce() -> None:
        invite = await ctx.session.get(StaffInvite, invite_id)
        if invite is None or invite.outlet_id != ctx.outlet_id:
            raise not_found("Invite")
        assert_can(ctx.actor, _capability_for(Role(invite.role)), ctx.outlet_id)
        if invite.accepted_at is None and invite.revoked_at is None:
            invite.revoked_at = datetime.now(UTC)
            await ctx.session.flush()
            audit(ctx, "staff.invite_revoked", "staff_invite", invite.id)

    await idempotent_write(ctx, key, f"DELETE invites/{invite_id}", None, type(None), produce)
