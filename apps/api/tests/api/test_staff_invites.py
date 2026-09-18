from __future__ import annotations

import re
import uuid
from urllib.parse import unquote

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth import decode_token
from app.core.permissions import Role
from tests.conftest import Seed, hdr, new_phone


def _otp(capsys: pytest.CaptureFixture[str], phone: str) -> str:
    match = re.search(rf"OTP for {re.escape(phone)}: (\d{{6}})", capsys.readouterr().out)
    assert match, "OTP was not printed"
    return match.group(1)


class Invitee:
    """Runs the whole invite flow so a test gets a real, freshly created staff member."""

    def __init__(
        self, client: httpx.AsyncClient, seed: Seed, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.client, self.seed, self.capsys = client, seed, capsys
        self.base = f"/v1/outlets/{seed.outlet_a}"
        self.owner = hdr(seed.token(seed.owner_a, Role.OWNER))

    async def invite(
        self, phone: str, role: str = "waiter", headers: dict[str, str] | None = None
    ) -> httpx.Response:
        return await self.client.post(
            f"{self.base}/invites",
            json={"phone": phone, "role": role},
            headers=headers or self.owner,
        )

    async def accept(self, token: str, phone: str, name: str | None = "New Hire") -> httpx.Response:
        self.capsys.readouterr()  # discard codes printed by earlier requests
        await self.client.post("/v1/invites/otp", json={"token": token})
        code = _otp(self.capsys, phone)
        return await self.client.post(
            "/v1/invites/accept", json={"token": token, "code": code, "name": name}
        )

    async def onboard(self, role: str = "waiter") -> tuple[str, str, dict[str, str]]:
        phone = new_phone()
        created = await self.invite(phone, role)
        assert created.status_code == 201, created.text
        token = created.json()["link"].rsplit("/", 1)[1]
        accepted = await self.accept(token, phone)
        assert accepted.status_code == 200, accepted.text
        return phone, token, hdr(accepted.json()["access_token"])


@pytest.fixture
def invitee(client: httpx.AsyncClient, seed: Seed, capsys: pytest.CaptureFixture[str]) -> Invitee:
    return Invitee(client, seed, capsys)


async def test_invite_flow_end_to_end(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    phone = new_phone()
    created = await invitee.invite(phone)
    assert created.status_code == 201
    body = created.json()
    assert body["link"].startswith("http://localhost:3001/invite/")
    assert body["whatsapp_url"].startswith(f"https://wa.me/{phone.lstrip('+')}?text=")
    assert body["link"] in unquote(body["whatsapp_url"])

    token = body["link"].rsplit("/", 1)[1]
    accepted = await invitee.accept(token, phone, name="Ravi")
    assert accepted.status_code == 200
    user_id, claims = decode_token(accepted.json()["access_token"])
    assert [(c.restaurant_id, c.outlet_id, c.role) for c in claims] == [
        (seed.restaurant_a, seed.outlet_a, Role.WAITER)
    ]
    tables = await client.get(
        f"{invitee.base}/tables", headers=hdr(accepted.json()["access_token"])
    )
    assert tables.status_code == 200

    again = await client.post("/v1/invites/accept", json={"token": token, "code": "123456"})
    assert (again.status_code, again.json()["code"]) == (410, "invite_invalid")
    pending = await client.get(f"{invitee.base}/invites", headers=invitee.owner)
    assert phone not in [i["phone"] for i in pending.json()]
    staff = await client.get(f"{invitee.base}/staff", headers=invitee.owner)
    assert any(s["phone"] == phone and s["name"] == "Ravi" and s["active"] for s in staff.json())


async def test_wrong_code_is_refused_and_invite_stays_usable(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    phone = new_phone()
    token = (await invitee.invite(phone)).json()["link"].rsplit("/", 1)[1]
    await client.post("/v1/invites/otp", json={"token": token})
    bad = await client.post("/v1/invites/accept", json={"token": token, "code": "000000"})
    assert (bad.status_code, bad.json()["code"]) == (401, "invalid_otp")
    assert (await invitee.accept(token, phone)).status_code == 200


async def test_unknown_token_gets_202_for_otp_and_410_for_accept(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    token = "x" * 43
    assert (await client.post("/v1/invites/otp", json={"token": token})).status_code == 202
    assert "OTP for" not in capsys.readouterr().out
    assert (
        await client.post("/v1/invites/accept", json={"token": token, "code": "123456"})
    ).status_code == 410


async def test_invite_otp_requests_are_rate_limited(client: httpx.AsyncClient) -> None:
    token = uuid.uuid4().hex + uuid.uuid4().hex
    statuses = [
        (await client.post("/v1/invites/otp", json={"token": token})).status_code for _ in range(6)
    ]
    assert statuses == [202] * 5 + [429]


async def test_manager_may_invite_waiters_only(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    manager = hdr(seed.token(seed.manager_a, Role.MANAGER))
    assert (await invitee.invite(new_phone(), "waiter", manager)).status_code == 201
    for role in ("manager", "kitchen", "bar", "owner"):
        r = await invitee.invite(new_phone(), role, manager)
        assert r.status_code == 403, role
    waiter = hdr(seed.token(seed.waiter_a, Role.WAITER))
    assert (await invitee.invite(new_phone(), "waiter", waiter)).status_code == 403
    assert (await invitee.invite(new_phone(), "manager")).status_code == 201  # owner may


async def test_reinviting_replaces_the_pending_invite(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    phone = new_phone()
    first = (await invitee.invite(phone)).json()["link"].rsplit("/", 1)[1]
    second = (await invitee.invite(phone)).json()["link"].rsplit("/", 1)[1]
    stale = await client.post("/v1/invites/accept", json={"token": first, "code": "123456"})
    assert stale.status_code == 410
    assert (await invitee.accept(second, phone)).status_code == 200


async def test_cannot_invite_someone_who_already_has_the_role(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    r = await invitee.invite(seed.phones["waiter_a"], "waiter")
    assert (r.status_code, r.json()["code"]) == (409, "already_staff")


async def test_expired_and_revoked_invites_cannot_be_accepted(
    client: httpx.AsyncClient,
    seed: Seed,
    invitee: Invitee,
    owner_engine: AsyncEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    phone = new_phone()
    created = (await invitee.invite(phone)).json()
    token = created["link"].rsplit("/", 1)[1]
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE staff_invite SET expires_at = now() - interval '1 minute' WHERE id = :i"),
            {"i": created["id"]},
        )
    assert (await client.post("/v1/invites/otp", json={"token": token})).status_code == 202
    assert "OTP for" not in capsys.readouterr().out
    assert (
        await client.post("/v1/invites/accept", json={"token": token, "code": "123456"})
    ).status_code == 410

    phone2 = new_phone()
    live = (await invitee.invite(phone2)).json()
    revoked = await client.delete(f"{invitee.base}/invites/{live['id']}", headers=invitee.owner)
    assert revoked.status_code == 204
    gone = await client.post(
        "/v1/invites/accept", json={"token": live["link"].rsplit("/", 1)[1], "code": "123456"}
    )
    assert gone.status_code == 410
    assert (
        await client.delete(f"{invitee.base}/invites/{live['id']}", headers=invitee.owner)
    ).status_code == 204  # idempotent
    assert (
        await client.delete(f"{invitee.base}/invites/{uuid.uuid4()}", headers=invitee.owner)
    ).status_code == 404


async def test_manager_cannot_revoke_a_non_waiter_invite(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    invite = (await invitee.invite(new_phone(), "kitchen")).json()
    r = await client.delete(
        f"{invitee.base}/invites/{invite['id']}",
        headers=hdr(seed.token(seed.manager_a, Role.MANAGER)),
    )
    assert r.status_code == 403


async def test_existing_user_gains_a_second_role_and_inactive_role_is_reactivated(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    phone, _, waiter = await invitee.onboard("waiter")
    kitchen_token = (await invitee.invite(phone, "kitchen")).json()["link"].rsplit("/", 1)[1]
    accepted = await invitee.accept(kitchen_token, phone, name=None)
    _, claims = decode_token(accepted.json()["access_token"])
    assert {c.role for c in claims} == {Role.WAITER, Role.KITCHEN}

    staff = (await client.get(f"{invitee.base}/staff", headers=invitee.owner)).json()
    waiter_row = next(s for s in staff if s["phone"] == phone and s["role"] == "waiter")
    await client.patch(
        f"{invitee.base}/staff/{waiter_row['id']}", json={"active": False}, headers=invitee.owner
    )
    again = (await invitee.invite(phone, "waiter")).json()["link"].rsplit("/", 1)[1]
    await invitee.accept(again, phone)
    staff = (await client.get(f"{invitee.base}/staff", headers=invitee.owner)).json()
    rows = [s for s in staff if s["phone"] == phone and s["role"] == "waiter"]
    assert len(rows) == 1 and rows[0]["active"] is True and rows[0]["id"] == waiter_row["id"]


async def test_deactivating_staff_takes_effect_on_their_very_next_request(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    phone, _, waiter = await invitee.onboard()
    assert (await client.get(f"{invitee.base}/tables", headers=waiter)).status_code == 200
    staff = (await client.get(f"{invitee.base}/staff", headers=invitee.owner)).json()
    row = next(s for s in staff if s["phone"] == phone)

    manager = hdr(seed.token(seed.manager_a, Role.MANAGER))
    off = await client.patch(
        f"{invitee.base}/staff/{row['id']}", json={"active": False}, headers=manager
    )
    assert off.status_code == 200 and off.json()["active"] is False
    # Same JWT, still unexpired: the database no longer grants the role.
    assert (await client.get(f"{invitee.base}/tables", headers=waiter)).status_code == 403
    on = await client.patch(
        f"{invitee.base}/staff/{row['id']}", json={"active": True}, headers=manager
    )
    assert on.status_code == 200
    assert (await client.get(f"{invitee.base}/tables", headers=waiter)).status_code == 200


async def test_staff_permissions_by_role(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    _, _, _ = await invitee.onboard("kitchen")
    staff = (await client.get(f"{invitee.base}/staff", headers=invitee.owner)).json()
    kitchen_row = next(
        s for s in staff if s["role"] == "kitchen" and s["phone"].startswith("+91999")
    )
    manager = hdr(seed.token(seed.manager_a, Role.MANAGER))
    assert (
        await client.patch(
            f"{invitee.base}/staff/{kitchen_row['id']}", json={"active": False}, headers=manager
        )
    ).status_code == 403

    waiter_row = next(s for s in staff if s["role"] == "waiter" and s["active"])
    role_change = await client.patch(
        f"{invitee.base}/staff/{waiter_row['id']}", json={"role": "bar"}, headers=manager
    )
    assert role_change.status_code == 403  # managers cannot change roles at all
    owner_change = await client.patch(
        f"{invitee.base}/staff/{waiter_row['id']}", json={"role": "bar"}, headers=invitee.owner
    )
    assert owner_change.json()["role"] == "bar"
    await client.patch(
        f"{invitee.base}/staff/{waiter_row['id']}", json={"role": "waiter"}, headers=invitee.owner
    )

    assert (
        await client.patch(
            f"{invitee.base}/staff/{uuid.uuid4()}", json={"active": False}, headers=invitee.owner
        )
    ).status_code == 404
    kitchen = hdr(seed.token(seed.kitchen_a, Role.KITCHEN))
    assert (await client.get(f"{invitee.base}/staff", headers=kitchen)).status_code == 403


async def test_last_active_owner_cannot_be_removed(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    staff = (await client.get(f"{invitee.base}/staff", headers=invitee.owner)).json()
    owner_row = next(s for s in staff if s["role"] == "owner")
    for body in ({"active": False}, {"role": "manager"}):
        r = await client.patch(
            f"{invitee.base}/staff/{owner_row['id']}", json=body, headers=invitee.owner
        )
        assert (r.status_code, r.json()["code"]) == (409, "last_owner")

    _, _, second_owner = await invitee.onboard("owner")
    second = next(
        s
        for s in (await client.get(f"{invitee.base}/staff", headers=invitee.owner)).json()
        if s["role"] == "owner" and s["id"] != owner_row["id"]
    )
    assert (
        await client.patch(
            f"{invitee.base}/staff/{second['id']}", json={"active": False}, headers=invitee.owner
        )
    ).status_code == 200


async def test_other_tenants_cannot_manage_this_staff(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    other = hdr(seed.token(seed.owner_b, Role.OWNER, tenant="b"))
    staff = (await client.get(f"{invitee.base}/staff", headers=invitee.owner)).json()
    victim = staff[0]["id"]
    assert (
        await client.patch(f"{invitee.base}/staff/{victim}", json={"active": False}, headers=other)
    ).status_code == 403
    via_b = await client.patch(
        f"/v1/outlets/{seed.outlet_b}/staff/{victim}", json={"active": False}, headers=other
    )
    assert via_b.status_code == 404
    assert (
        await client.post(
            f"{invitee.base}/invites", json={"phone": new_phone(), "role": "waiter"}, headers=other
        )
    ).status_code == 403


async def test_invite_station_must_belong_to_the_outlet(
    client: httpx.AsyncClient, seed: Seed, invitee: Invitee
) -> None:
    other_base = f"/v1/outlets/{seed.outlet_b}"
    other_owner = hdr(seed.token(seed.owner_b, Role.OWNER, tenant="b"))
    foreign = (
        await client.post(f"{other_base}/stations", json={"name": "B Kitchen"}, headers=other_owner)
    ).json()
    r = await client.post(
        f"{invitee.base}/invites",
        json={"phone": new_phone(), "role": "kitchen", "station_id": foreign["id"]},
        headers=invitee.owner,
    )
    assert r.status_code == 404
    await client.delete(f"{other_base}/stations/{foreign['id']}", headers=other_owner)
