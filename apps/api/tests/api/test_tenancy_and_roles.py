from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.auth import RoleClaim, issue_token
from app.core.permissions import Role
from app.db.session import anonymous_session, tenant_session
from tests.conftest import Seed, bearer


async def test_app_role_cannot_bypass_rls() -> None:
    """Superusers and BYPASSRLS roles skip every policy, so the runtime role
    must be neither. Fails loudly if the DB is set up with `app` as bootstrap user."""
    async with anonymous_session() as session:
        row = (
            await session.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    assert (row.rolsuper, row.rolbypassrls) == (False, False)


async def test_manager_lists_own_outlet_tables(client: httpx.AsyncClient, seed: Seed) -> None:
    r = await client.get(
        f"/v1/outlets/{seed.outlet_a}/tables",
        headers=bearer(seed.token(seed.manager_a, Role.MANAGER)),
    )
    assert r.status_code == 200
    assert [t["label"] for t in r.json()] == ["T1", "T2"]


async def test_user_of_tenant_a_is_refused_outlet_of_tenant_b(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    r = await client.get(
        f"/v1/outlets/{seed.outlet_b}/tables",
        headers=bearer(seed.token(seed.manager_a, Role.MANAGER)),
    )
    assert r.status_code == 403
    assert r.json()["code"] == "permission_denied"


async def test_rls_returns_zero_rows_even_if_a_claim_points_at_another_tenants_outlet(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    """Backstop: pretend a bug or stale token lets tenant A's restaurant id
    pair with tenant B's outlet. The API layer is satisfied, so only the
    database stands between A and B's rows. Result must be empty, not an error."""
    forged = issue_token(
        seed.manager_a, [RoleClaim(seed.restaurant_a, seed.outlet_b, Role.MANAGER)]
    )
    r = await client.get(f"/v1/outlets/{seed.outlet_b}/tables", headers=bearer(forged))
    assert r.status_code == 200
    assert r.json() == []


async def test_tenant_session_sees_only_its_own_rows(seed: Seed) -> None:
    async with tenant_session(seed.restaurant_a) as session:
        own = await session.scalar(
            text("SELECT count(*) FROM outlet WHERE id = :i"), {"i": seed.outlet_a}
        )
        other = await session.scalar(
            text("SELECT count(*) FROM outlet WHERE id = :i"), {"i": seed.outlet_b}
        )
        restaurants = await session.scalar(
            text("SELECT count(*) FROM restaurant WHERE id = ANY(:i)"),
            {"i": [seed.restaurant_a, seed.restaurant_b]},
        )
    assert (own, other, restaurants) == (1, 0, 1)


async def test_tenant_session_cannot_write_into_another_tenant(seed: Seed) -> None:
    with pytest.raises(DBAPIError):
        async with tenant_session(seed.restaurant_a) as session:
            await session.execute(
                text(
                    "INSERT INTO station (id, restaurant_id, outlet_id, name) "
                    "VALUES (gen_random_uuid(), :rid, :oid, 'Bar')"
                ),
                {"rid": seed.restaurant_b, "oid": seed.outlet_b},
            )


async def test_session_without_tenant_context_sees_nothing_and_does_not_error(seed: Seed) -> None:
    # A pooled connection that already ran a tenant transaction keeps the
    # setting defined as '' afterwards; the policy must treat that as "no tenant".
    async with tenant_session(seed.restaurant_a) as session:
        await session.execute(text("SELECT 1"))
    async with anonymous_session() as session:
        for table in (
            "outlet",
            "dining_table",
            "staff_role",
            "menu_item",
            "audit_log",
            "restaurant",
        ):
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0


async def test_waiter_gets_403_on_manager_only_endpoint(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    r = await client.get(
        f"/v1/outlets/{seed.outlet_a}/staff",
        headers=bearer(seed.token(seed.waiter_a, Role.WAITER)),
    )
    assert r.status_code == 403
    assert r.json()["code"] == "permission_denied"


async def test_manager_can_list_staff_of_own_outlet_only(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    r = await client.get(
        f"/v1/outlets/{seed.outlet_a}/staff",
        headers=bearer(seed.token(seed.manager_a, Role.MANAGER)),
    )
    assert r.status_code == 200
    assert {s["role"] for s in r.json()} == {"manager", "waiter", "kitchen"}
    assert len(r.json()) == 4


async def test_kitchen_cannot_view_tables(client: httpx.AsyncClient, seed: Seed) -> None:
    r = await client.get(
        f"/v1/outlets/{seed.outlet_a}/tables",
        headers=bearer(seed.token(seed.kitchen_a, Role.KITCHEN)),
    )
    assert r.status_code == 403


async def test_missing_token_is_401(client: httpx.AsyncClient, seed: Seed) -> None:
    r = await client.get(f"/v1/outlets/{seed.outlet_a}/tables")
    assert r.status_code == 401
    assert r.json()["code"] == "not_authenticated"


@pytest.mark.parametrize("token", ["garbage", ""])
async def test_bad_token_is_401(client: httpx.AsyncClient, seed: Seed, token: str) -> None:
    r = await client.get(f"/v1/outlets/{seed.outlet_a}/tables", headers=bearer(token))
    assert r.status_code == 401


async def test_expired_token_is_401(
    client: httpx.AsyncClient, seed: Seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.auth.settings.jwt_access_token_ttl_seconds", -10)
    token = seed.token(seed.manager_a, Role.MANAGER)
    r = await client.get(f"/v1/outlets/{seed.outlet_a}/tables", headers=bearer(token))
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_token"


async def test_token_signed_with_another_secret_is_401(
    client: httpx.AsyncClient, seed: Seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.auth.settings.jwt_secret", "some-other-secret-value-32-bytes-min!!")
    token = seed.token(seed.manager_a, Role.MANAGER)
    monkeypatch.undo()
    r = await client.get(f"/v1/outlets/{seed.outlet_a}/tables", headers=bearer(token))
    assert r.status_code == 401
