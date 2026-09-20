"""The per-agent key a voice agent's tools send in `X-Voice-Key`.

Same shape and rules as a guest's TabSession token (docs/DECISIONS.md "Milestone 3 choices"):
`<restaurant_id hex>.<random>`, only a SHA-256 of the random part is stored. The prefix says
which tenant to open a session for, the hash proves possession, and RLS still confines every
query to that tenant, so no cross-tenant policy is needed to look the agent up.
"""

from __future__ import annotations

import hmac
import secrets
from uuid import UUID

from app.auth import InvalidTokenError
from app.guest_auth import hash_secret, parse_session_token


def new_voice_key(restaurant_id: UUID) -> tuple[str, str]:
    """Returns (key to give the platform, hash to store)."""
    secret = secrets.token_urlsafe(32)
    return f"{restaurant_id.hex}.{secret}", hash_secret(secret)


def parse_voice_key(key: str) -> tuple[UUID, str]:
    """Returns (restaurant_id, hash to compare). Raises InvalidTokenError."""
    return parse_session_token(key)


def matches(stored_hash: str, presented_hash: str) -> bool:
    return hmac.compare_digest(stored_hash, presented_hash)


__all__ = ["InvalidTokenError", "matches", "new_voice_key", "parse_voice_key"]
