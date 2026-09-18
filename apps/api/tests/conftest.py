from __future__ import annotations

import random
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.auth import RoleClaim, issue_token
from app.config import settings
from app.core.permissions import Role
from app.main import app


@dataclass(frozen=True)
class Seed:
    restaurant_a: uuid.UUID
    restaurant_b: uuid.UUID
    outlet_a: uuid.UUID
    outlet_b: uuid.UUID
    manager_a: uuid.UUID
    waiter_a: uuid.UUID
    kitchen_a: uuid.UUID
    inactive_waiter_a: uuid.UUID
    manager_b: uuid.UUID
    phones: dict[str, str]

    def token(self, user_id: uuid.UUID, role: Role, *, tenant: str = "a") -> str:
        restaurant, outlet = (
            (self.restaurant_a, self.outlet_a)
            if tenant == "a"
            else (self.restaurant_b, self.outlet_b)
        )
        return issue_token(user_id, [RoleClaim(restaurant, outlet, role)])


def _phone() -> str:
    return f"+919{random.randint(10**8, 10**9 - 1)}"


@pytest.fixture(scope="session")
async def owner_engine() -> AsyncIterator[AsyncEngine]:
    """The table-owner role. Bypasses RLS, so it is used only to seed and
    clean up test data, never to exercise the API."""
    engine = create_async_engine(settings.migration_database_url or settings.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def seed(owner_engine: AsyncEngine) -> AsyncIterator[Seed]:
    ids = {
        k: uuid.uuid4()
        for k in (
            "restaurant_a",
            "restaurant_b",
            "outlet_a",
            "outlet_b",
            "manager_a",
            "waiter_a",
            "kitchen_a",
            "inactive_waiter_a",
            "manager_b",
        )
    }
    phones = {
        k: _phone()
        for k in ("manager_a", "waiter_a", "kitchen_a", "inactive_waiter_a", "manager_b")
    }
    async with owner_engine.begin() as conn:
        for tenant in ("a", "b"):
            rid, oid = ids[f"restaurant_{tenant}"], ids[f"outlet_{tenant}"]
            await conn.execute(
                text("INSERT INTO restaurant (id, legal_name, brand_name) VALUES (:id, 'L', :n)"),
                {"id": rid, "n": f"Brand {tenant}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO outlet (id, restaurant_id, name, state_code, invoice_prefix) "
                    "VALUES (:id, :rid, 'Main', 'KA', 'INV')"
                ),
                {"id": oid, "rid": rid},
            )
        for label, tenant in (("T1", "a"), ("T2", "a"), ("T9", "b")):
            await conn.execute(
                text(
                    "INSERT INTO dining_table (id, restaurant_id, outlet_id, label, qr_token) "
                    "VALUES (:id, :rid, :oid, :label, :qr)"
                ),
                {
                    "id": uuid.uuid4(),
                    "rid": ids[f"restaurant_{tenant}"],
                    "oid": ids[f"outlet_{tenant}"],
                    "label": label,
                    "qr": uuid.uuid4().hex,
                },
            )
        roles = [
            ("manager_a", "a", "manager", True),
            ("waiter_a", "a", "waiter", True),
            ("kitchen_a", "a", "kitchen", True),
            ("inactive_waiter_a", "a", "waiter", False),
            ("manager_b", "b", "manager", True),
        ]
        for key, tenant, role, active in roles:
            await conn.execute(
                text("INSERT INTO app_user (id, phone) VALUES (:id, :phone)"),
                {"id": ids[key], "phone": phones[key]},
            )
            await conn.execute(
                text(
                    "INSERT INTO staff_role (id, restaurant_id, user_id, outlet_id, role, active) "
                    "VALUES (:id, :rid, :uid, :oid, :role, :active)"
                ),
                {
                    "id": uuid.uuid4(),
                    "rid": ids[f"restaurant_{tenant}"],
                    "uid": ids[key],
                    "oid": ids[f"outlet_{tenant}"],
                    "role": role,
                    "active": active,
                },
            )
    yield Seed(phones=phones, **ids)
    rids = [ids["restaurant_a"], ids["restaurant_b"]]
    uids = [ids[k] for k in phones]
    async with owner_engine.begin() as conn:
        for table in ("audit_log", "staff_role", "dining_table", "outlet"):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE restaurant_id = ANY(:r)"), {"r": rids}
            )
        await conn.execute(text("DELETE FROM restaurant WHERE id = ANY(:r)"), {"r": rids})
        await conn.execute(text("DELETE FROM app_user WHERE id = ANY(:u)"), {"u": uids})


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
