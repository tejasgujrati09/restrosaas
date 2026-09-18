"""Public (unauthenticated) invite acceptance: the invitee proves they hold the
invited phone number by OTP, then receives a normal login token."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.api.v1.auth import TokenOut
from app.api.v1.staff import hash_token
from app.auth import issue_token, otp_store
from app.config import settings
from app.db.session import anonymous_session, invite_session, tenant_session
from app.domains.staff.models import AppUser, AuditLog, StaffInvite, StaffRole
from app.domains.staff.service import load_claims
from app.errors import ApiError

router = APIRouter(prefix="/v1/invites", tags=["invites"])


class InviteOtpIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class InviteAcceptIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    code: str = Field(min_length=6, max_length=6)
    name: str | None = Field(default=None, max_length=100)


def _usable(invite: StaffInvite) -> bool:
    return (
        invite.accepted_at is None
        and invite.revoked_at is None
        and invite.expires_at > datetime.now(UTC)
    )


@router.post("/otp", status_code=202)
async def request_invite_otp(body: InviteOtpIn) -> None:
    """Always 202, so the endpoint does not reveal which tokens are real."""
    token_hash = hash_token(body.token)
    otp_store.throttle(f"invite-request:{token_hash}")
    async with invite_session(token_hash) as session:
        invite = await session.scalar(
            select(StaffInvite).where(StaffInvite.token_hash == token_hash)
        )
        phone = invite.phone if invite is not None and _usable(invite) else None
    if phone is None:
        return
    code = otp_store.issue(f"invite:{token_hash}")
    if settings.otp_dev_mode:
        print(f"[dev] OTP for {phone}: {code}", flush=True)  # noqa: T201


@router.post("/accept")
async def accept_invite(body: InviteAcceptIn) -> TokenOut:
    token_hash = hash_token(body.token)
    gone = ApiError(410, "invite_invalid", "This invite is no longer valid. Ask for a new one.")
    async with invite_session(token_hash) as session:
        found = await session.scalar(
            select(StaffInvite).where(StaffInvite.token_hash == token_hash)
        )
        if found is None or not _usable(found):
            raise gone
        restaurant_id, invite_id, phone = found.restaurant_id, found.id, found.phone
    if not otp_store.verify(f"invite:{token_hash}", body.code):
        raise ApiError(401, "invalid_otp", "That code is not right. Try again.")

    async with anonymous_session() as session:
        await session.execute(
            insert(AppUser)
            .values(phone=phone, name=body.name)
            .on_conflict_do_nothing(index_elements=[AppUser.phone])
        )
        user = await session.scalar(select(AppUser).where(AppUser.phone == phone))
        assert user is not None
        if body.name and not user.name:
            user.name = body.name
        user_id = user.id

    async with tenant_session(restaurant_id) as session:
        invite = await session.scalar(
            select(StaffInvite).where(StaffInvite.id == invite_id).with_for_update()
        )
        if invite is None or not _usable(invite):
            raise gone
        invite.accepted_at = datetime.now(UTC)
        role = await session.scalar(
            select(StaffRole).where(
                StaffRole.user_id == user_id,
                StaffRole.outlet_id == invite.outlet_id,
                StaffRole.role == invite.role,
            )
        )
        if role is None:
            session.add(
                StaffRole(
                    restaurant_id=restaurant_id,
                    user_id=user_id,
                    outlet_id=invite.outlet_id,
                    role=invite.role,
                    station_id=invite.station_id,
                )
            )
        else:
            role.active = True
        session.add(
            AuditLog(
                actor_user_id=user_id,
                restaurant_id=restaurant_id,
                action="staff.invite_accepted",
                target_type="staff_invite",
                target_id=invite.id,
                after={"role": invite.role},
            )
        )
    return TokenOut(access_token=issue_token(user_id, await load_claims(user_id)))
