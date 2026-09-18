from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from uuid import UUID

import jwt

from app.config import settings
from app.core.permissions import Role

OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
OTP_MAX_REQUESTS = 5
OTP_REQUEST_WINDOW_SECONDS = 900


@dataclass(frozen=True)
class RoleClaim:
    restaurant_id: UUID
    outlet_id: UUID
    role: Role


class InvalidTokenError(Exception):
    pass


def issue_token(user_id: UUID, roles: list[RoleClaim]) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + settings.jwt_access_token_ttl_seconds,
        "roles": [
            {"restaurant_id": str(r.restaurant_id), "outlet_id": str(r.outlet_id), "role": r.role}
            for r in roles
        ],
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> tuple[UUID, list[RoleClaim]]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iss"]},
        )
        roles = [
            RoleClaim(UUID(r["restaurant_id"]), UUID(r["outlet_id"]), Role(r["role"]))
            for r in payload["roles"]
        ]
        return UUID(payload["sub"]), roles
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise InvalidTokenError from exc


class OtpRateLimitedError(Exception):
    pass


class OtpStore:
    """In-process OTP stub for development. Replace with Redis plus a
    WhatsApp/SMS sender before any real deployment (Milestone 5 job queue)."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[str, float, int]] = {}
        self._requests: dict[str, list[float]] = {}

    def throttle(self, key: str) -> None:
        """Count a code request against `key`; raise after too many in the window.
        Call this before looking the phone up so the limit is identical for known
        and unknown numbers and cannot be used to discover which are registered."""
        now = time.monotonic()
        recent = [t for t in self._requests.get(key, []) if now - t < OTP_REQUEST_WINDOW_SECONDS]
        if len(recent) >= OTP_MAX_REQUESTS:
            self._requests[key] = recent
            raise OtpRateLimitedError
        self._requests[key] = [*recent, now]

    def issue(self, phone: str) -> str:
        code = settings.otp_dev_fixed_code or f"{secrets.randbelow(1_000_000):06d}"
        self._entries[phone] = (code, time.monotonic() + OTP_TTL_SECONDS, 0)
        return code

    def verify(self, phone: str, code: str) -> bool:
        entry = self._entries.get(phone)
        if entry is None:
            return False
        stored, expires_at, attempts = entry
        if time.monotonic() > expires_at or attempts >= OTP_MAX_ATTEMPTS:
            del self._entries[phone]
            return False
        if not secrets.compare_digest(stored, code):
            self._entries[phone] = (stored, expires_at, attempts + 1)
            return False
        del self._entries[phone]
        return True


otp_store = OtpStore()
