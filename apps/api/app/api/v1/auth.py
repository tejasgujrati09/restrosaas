from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth import RoleClaim, issue_token, otp_store
from app.config import settings
from app.core.permissions import Role
from app.db.session import anonymous_session, login_session
from app.domains.staff.models import AppUser, StaffRole
from app.errors import ApiError

router = APIRouter(prefix="/v1/auth", tags=["auth"])
logger = structlog.get_logger()

_PHONE_PATTERN = r"^\+[1-9][0-9]{7,14}$"


class OtpRequestIn(BaseModel):
    phone: str = Field(pattern=_PHONE_PATTERN)


class OtpVerifyIn(BaseModel):
    phone: str = Field(pattern=_PHONE_PATTERN)
    code: str = Field(min_length=6, max_length=6)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/otp/request", status_code=202)
async def request_otp(body: OtpRequestIn) -> None:
    """Always 202, whether or not the phone belongs to a user, so the
    endpoint cannot be used to discover staff phone numbers."""
    async with anonymous_session() as session:
        user_id = await session.scalar(select(AppUser.id).where(AppUser.phone == body.phone))
    if user_id is None:
        return
    code = otp_store.issue(body.phone)
    if settings.otp_dev_mode:
        print(f"[dev] OTP for {body.phone}: {code}", flush=True)  # noqa: T201
    else:
        logger.warning("otp_delivery_not_configured")


@router.post("/otp/verify")
async def verify_otp(body: OtpVerifyIn) -> TokenOut:
    invalid = ApiError(401, "invalid_otp", "That code is not right. Try again.")
    if not otp_store.verify(body.phone, body.code):
        raise invalid
    async with anonymous_session() as session:
        user = await session.scalar(select(AppUser).where(AppUser.phone == body.phone))
        if user is None:
            raise invalid
        user.last_login_at = datetime.now(UTC)
        user_id = user.id
    async with login_session(user_id) as session:
        rows = await session.execute(
            select(StaffRole.restaurant_id, StaffRole.outlet_id, StaffRole.role).where(
                StaffRole.user_id == user_id, StaffRole.active.is_(True)
            )
        )
        claims = [RoleClaim(r.restaurant_id, r.outlet_id, Role(r.role)) for r in rows]
    return TokenOut(access_token=issue_token(user_id, claims))
