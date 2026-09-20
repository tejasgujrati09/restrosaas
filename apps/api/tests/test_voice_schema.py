"""Tenant isolation and integrity for the voice tables (migration 0009).

Fixture data only: fake phones from `new_phone()` and obviously fake addresses."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import anonymous_session, tenant_session
from tests.conftest import Seed, new_phone


@pytest.fixture
async def customer_a(seed: Seed, owner_engine: AsyncEngine) -> AsyncIterator[dict[str, uuid.UUID]]:
    ids = {"customer": uuid.uuid4(), "address": uuid.uuid4()}
    async with tenant_session(seed.restaurant_a) as session:
        await session.execute(
            text(
                "INSERT INTO customer (id, restaurant_id, phone, name, created_at) "
                "VALUES (:id, :rid, :phone, 'Test Caller', :now)"
            ),
            {"id": ids["customer"], "rid": seed.restaurant_a, "phone": new_phone(), "now": _now()},
        )
        await session.execute(
            text(
                "INSERT INTO customer_address "
                "(id, restaurant_id, customer_id, address_text, is_preferred, created_at) "
                "VALUES (:id, :rid, :cid, '1 Test Street, Testville', true, :now)"
            ),
            {
                "id": ids["address"],
                "rid": seed.restaurant_a,
                "cid": ids["customer"],
                "now": _now(),
            },
        )
    yield ids
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM customer_address WHERE customer_id = :c"), {"c": ids["customer"]}
        )
        await conn.execute(text("DELETE FROM customer WHERE id = :c"), {"c": ids["customer"]})


def _now() -> datetime:
    return datetime.now(UTC)


@pytest.mark.parametrize("table", ["customer", "customer_address", "voice_agent"])
async def test_other_tenant_and_no_tenant_read_zero_rows(
    seed: Seed, customer_a: dict[str, uuid.UUID], table: str
) -> None:
    async with tenant_session(seed.restaurant_a) as session:
        if table != "voice_agent":
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) >= 1
    async with tenant_session(seed.restaurant_b) as session:
        assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0
    async with anonymous_session() as session:
        assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0


async def test_tenant_cannot_write_a_row_for_another_restaurant(seed: Seed) -> None:
    with pytest.raises(DBAPIError):
        async with tenant_session(seed.restaurant_b) as session:
            await session.execute(
                text(
                    "INSERT INTO customer (id, restaurant_id, phone, created_at) "
                    "VALUES (:id, :rid, :phone, :now)"
                ),
                {"id": uuid.uuid4(), "rid": seed.restaurant_a, "phone": new_phone(), "now": _now()},
            )


async def test_phone_is_unique_per_restaurant(seed: Seed, customer_a: dict[str, uuid.UUID]) -> None:
    async with tenant_session(seed.restaurant_a) as session:
        phone = await session.scalar(
            text("SELECT phone FROM customer WHERE id = :c"), {"c": customer_a["customer"]}
        )
    with pytest.raises(IntegrityError):
        async with tenant_session(seed.restaurant_a) as session:
            await session.execute(
                text(
                    "INSERT INTO customer (id, restaurant_id, phone, created_at) "
                    "VALUES (:id, :rid, :phone, :now)"
                ),
                {"id": uuid.uuid4(), "rid": seed.restaurant_a, "phone": phone, "now": _now()},
            )


async def test_only_one_preferred_address_per_customer(
    seed: Seed, customer_a: dict[str, uuid.UUID]
) -> None:
    with pytest.raises(IntegrityError):
        async with tenant_session(seed.restaurant_a) as session:
            await session.execute(
                text(
                    "INSERT INTO customer_address "
                    "(id, restaurant_id, customer_id, address_text, is_preferred, created_at) "
                    "VALUES (:id, :rid, :cid, '2 Test Street', true, :now)"
                ),
                {
                    "id": uuid.uuid4(),
                    "rid": seed.restaurant_a,
                    "cid": customer_a["customer"],
                    "now": _now(),
                },
            )


async def test_blank_address_is_refused(seed: Seed, customer_a: dict[str, uuid.UUID]) -> None:
    with pytest.raises(IntegrityError):
        async with tenant_session(seed.restaurant_a) as session:
            await session.execute(
                text(
                    "INSERT INTO customer_address "
                    "(id, restaurant_id, customer_id, address_text, created_at) "
                    "VALUES (:id, :rid, :cid, '   ', :now)"
                ),
                {
                    "id": uuid.uuid4(),
                    "rid": seed.restaurant_a,
                    "cid": customer_a["customer"],
                    "now": _now(),
                },
            )


async def test_address_cannot_point_at_another_restaurants_customer(
    seed: Seed, customer_a: dict[str, uuid.UUID]
) -> None:
    """The composite foreign key ties an address to a customer of the same restaurant, so
    a bug or a forged id cannot attach restaurant B's address to restaurant A's caller."""
    with pytest.raises(IntegrityError):
        async with tenant_session(seed.restaurant_b) as session:
            await session.execute(
                text(
                    "INSERT INTO customer_address "
                    "(id, restaurant_id, customer_id, address_text, created_at) "
                    "VALUES (:id, :rid, :cid, '9 Test Street', :now)"
                ),
                {
                    "id": uuid.uuid4(),
                    "rid": seed.restaurant_b,
                    "cid": customer_a["customer"],
                    "now": _now(),
                },
            )


async def test_one_voice_agent_per_outlet(seed: Seed, owner_engine: AsyncEngine) -> None:
    async def add() -> None:
        async with tenant_session(seed.restaurant_a) as session:
            await session.execute(
                text(
                    "INSERT INTO voice_agent (id, restaurant_id, outlet_id, key_hash, "
                    "created_at, updated_at) VALUES (:id, :rid, :oid, 'fixture-hash', :now, :now)"
                ),
                {
                    "id": uuid.uuid4(),
                    "rid": seed.restaurant_a,
                    "oid": seed.outlet_a,
                    "now": _now(),
                },
            )

    try:
        await add()
        with pytest.raises(IntegrityError):
            await add()
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM voice_agent WHERE outlet_id = :o"), {"o": seed.outlet_a}
            )
