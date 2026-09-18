"""Public self-serve signup: a phone number verified by OTP creates a
restaurant, its first outlet and an owner role (docs/DECISIONS.md "Signup")."""

from __future__ import annotations

import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.api.v1.auth import TokenOut
from app.api.v1.staff import PHONE_PATTERN
from app.auth import issue_token, otp_store
from app.config import settings
from app.core.permissions import Role
from app.db.session import tenant_session
from app.domains.staff.models import AppUser, AuditLog, StaffRole
from app.domains.staff.service import load_claims
from app.domains.tenant.models import Outlet, Restaurant
from app.errors import ApiError

router = APIRouter(prefix="/v1/signup", tags=["signup"])
logger = structlog.get_logger()


class SignupOtpIn(BaseModel):
    phone: str = Field(pattern=PHONE_PATTERN)


class SignupIn(BaseModel):
    phone: str = Field(pattern=PHONE_PATTERN)
    code: str = Field(min_length=6, max_length=6)
    owner_name: str | None = Field(default=None, max_length=100)
    legal_name: str = Field(min_length=1, max_length=200)
    brand_name: str = Field(min_length=1, max_length=200)
    outlet_name: str = Field(min_length=1, max_length=200)
    # GST state code, e.g. "29" for Karnataka.
    state_code: str = Field(pattern=r"^[0-9]{2}$")
    timezone: str = "Asia/Kolkata"


class SignupOut(TokenOut):
    restaurant_id: uuid.UUID
    outlet_id: uuid.UUID


@router.post("/otp", status_code=202)
async def request_signup_otp(body: SignupOtpIn) -> None:
    otp_store.throttle(f"signup-request:{body.phone}")
    code = otp_store.issue(f"signup:{body.phone}")
    if settings.otp_dev_mode:
        print(f"[dev] OTP for {body.phone}: {code}", flush=True)  # noqa: T201
    else:
        logger.warning("otp_delivery_not_configured")


@router.post("", status_code=201)
async def signup(body: SignupIn) -> SignupOut:
    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ApiError(422, "validation_error", "Unknown timezone.", {"field": "timezone"}) from exc
    if not otp_store.verify(f"signup:{body.phone}", body.code):
        raise ApiError(401, "invalid_otp", "That code is not right. Try again.")

    restaurant_id, outlet_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(restaurant_id) as session:
        session.add(
            Restaurant(id=restaurant_id, legal_name=body.legal_name, brand_name=body.brand_name)
        )
        await session.flush()
        session.add(
            Outlet(
                id=outlet_id,
                restaurant_id=restaurant_id,
                name=body.outlet_name,
                state_code=body.state_code,
                timezone=body.timezone,
                invoice_prefix="INV",
            )
        )
        await session.execute(
            insert(AppUser)
            .values(phone=body.phone, name=body.owner_name)
            .on_conflict_do_nothing(index_elements=[AppUser.phone])
        )
        user_id = await session.scalar(select(AppUser.id).where(AppUser.phone == body.phone))
        assert user_id is not None
        await session.flush()
        session.add(
            StaffRole(
                restaurant_id=restaurant_id,
                user_id=user_id,
                outlet_id=outlet_id,
                role=Role.OWNER.value,
            )
        )
        session.add(
            AuditLog(
                actor_user_id=user_id,
                restaurant_id=restaurant_id,
                action="restaurant.signed_up",
                target_type="restaurant",
                target_id=restaurant_id,
                after={"brand_name": body.brand_name},
            )
        )
    return SignupOut(
        access_token=issue_token(user_id, await load_claims(user_id)),
        restaurant_id=restaurant_id,
        outlet_id=outlet_id,
    )
