"""TabSession tokens: opaque bearer tokens for unauthenticated guests
(docs/DECISIONS.md "Milestone 3 choices").

Shape `<restaurant_id hex>.<random>`. Only a SHA-256 of the random part is
stored. The prefix says which tenant to open a session for; the hash proves
possession, and RLS still confines every query to that tenant.
"""

from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from app.auth import InvalidTokenError

SESSION_TTL_HOURS = 6


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def new_session_token(restaurant_id: UUID) -> tuple[str, str]:
    """Returns (token for the client, hash to store)."""
    secret = secrets.token_urlsafe(32)
    return f"{restaurant_id.hex}.{secret}", hash_secret(secret)


def parse_session_token(token: str) -> tuple[UUID, str]:
    """Returns (restaurant_id, hash to look up). Raises InvalidTokenError."""
    prefix, dot, secret = token.partition(".")
    if not dot or not secret or len(prefix) != 32:
        raise InvalidTokenError
    try:
        return UUID(hex=prefix), hash_secret(secret)
    except ValueError as exc:
        raise InvalidTokenError from exc
