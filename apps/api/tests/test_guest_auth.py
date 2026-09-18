from __future__ import annotations

from uuid import uuid4

import pytest

from app.auth import InvalidTokenError
from app.guest_auth import hash_secret, new_session_token, parse_session_token


def test_token_round_trips_to_the_stored_hash() -> None:
    restaurant_id = uuid4()
    token, stored_hash = new_session_token(restaurant_id)
    assert parse_session_token(token) == (restaurant_id, stored_hash)
    assert stored_hash == hash_secret(token.split(".", 1)[1])
    assert token != new_session_token(restaurant_id)[0]


@pytest.mark.parametrize(
    "bad",
    ["", "nodot", "abc.def", f"{'z' * 32}.secret", f"{uuid4().hex}.", "a.b.c", "eyJhbGciOi.x.y"],
)
def test_malformed_tokens_are_rejected(bad: str) -> None:
    with pytest.raises(InvalidTokenError):
        parse_session_token(bad)
