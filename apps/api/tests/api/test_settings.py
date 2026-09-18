from __future__ import annotations

import uuid

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.permissions import Role
from tests.conftest import Seed, hdr


def _gstin(state: str) -> str:
    """A GSTIN with a correct check character for the given state code."""
    from app.core.gstin import _ALPHABET, _check_char

    body = f"{state}AAPFU0939F1Z"
    return body + _check_char(body) if _ALPHABET else body


async def _patch(
    client: httpx.AsyncClient, seed: Seed, body: dict[str, object], *, role: Role = Role.OWNER
) -> httpx.Response:
    user = {Role.OWNER: seed.owner_a, Role.MANAGER: seed.manager_a, Role.WAITER: seed.waiter_a}[
        role
    ]
    return await client.patch(
        f"/v1/outlets/{seed.outlet_a}/settings", json=body, headers=hdr(seed.token(user, role))
    )


async def test_any_staff_role_can_read_settings(client: httpx.AsyncClient, seed: Seed) -> None:
    r = await client.get(
        f"/v1/outlets/{seed.outlet_a}/settings",
        headers=hdr(seed.token(seed.waiter_a, Role.WAITER)),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["prices_include_tax"] is True
    assert body["ack_threshold_paise"] == 50000
    assert body["next_invoice_preview"] == "INV/1"


async def test_only_owner_can_edit_settings(client: httpx.AsyncClient, seed: Seed) -> None:
    for role in (Role.MANAGER, Role.WAITER):
        r = await _patch(client, seed, {"waiter_confirm_mode": True}, role=role)
        assert r.status_code == 403


async def test_owner_updates_settings_and_readiness_tracks_gstin_and_tax_class(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    before = (await _patch(client, seed, {"state_code": "29"})).json()
    assert before["ready_to_go_live"] is False
    assert set(before["go_live_blockers"]) == {"Add your GSTIN.", "Add at least one tax class."}

    r = await _patch(
        client,
        seed,
        {"gstin": _gstin("29").lower(), "waiter_confirm_mode": True, "ack_threshold_paise": 70000},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["gstin"] == _gstin("29")  # normalised to upper case
    assert body["waiter_confirm_mode"] is True
    assert body["ack_threshold_paise"] == 70000
    assert body["go_live_blockers"] == ["Add at least one tax class."]

    await client.post(
        f"/v1/outlets/{seed.outlet_a}/tax-classes",
        json={"name": "Food 5%", "gst_rate_bp": 500},
        headers=hdr(seed.token(seed.owner_a, Role.OWNER)),
    )
    ready = await client.get(
        f"/v1/outlets/{seed.outlet_a}/settings", headers=hdr(seed.token(seed.owner_a, Role.OWNER))
    )
    assert ready.json()["ready_to_go_live"] is True


async def test_invalid_gstin_is_rejected(client: httpx.AsyncClient, seed: Seed) -> None:
    bad = _gstin("29")[:-1] + ("0" if _gstin("29")[-1] != "0" else "1")
    r = await _patch(client, seed, {"gstin": bad})
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")
    assert r.json()["details"]["field"] == "gstin"


async def test_gstin_state_must_match_outlet_state_code(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    await _patch(client, seed, {"state_code": "29"})
    r = await _patch(client, seed, {"gstin": _gstin("27")})
    assert r.status_code == 422
    assert "state code" in r.json()["message"]


async def test_unknown_timezone_is_rejected(client: httpx.AsyncClient, seed: Seed) -> None:
    r = await _patch(client, seed, {"timezone": "Mars/Olympus"})
    assert r.status_code == 422
    ok = await _patch(client, seed, {"timezone": "Asia/Kolkata"})
    assert ok.status_code == 200


async def test_invoice_prefix_change_is_audited_and_counter_is_untouched(
    client: httpx.AsyncClient, seed: Seed, owner_engine: AsyncEngine
) -> None:
    r = await _patch(client, seed, {"invoice_prefix": "FY27"})
    assert r.status_code == 200
    body = r.json()
    assert (body["invoice_prefix"], body["next_invoice_no"], body["next_invoice_preview"]) == (
        "FY27",
        1,
        "FY27/1",
    )
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT before, after, actor_user_id FROM audit_log "
                    "WHERE restaurant_id = :r AND action = 'outlet.invoice_prefix_changed' "
                    "ORDER BY at DESC LIMIT 1"
                ),
                {"r": seed.restaurant_a},
            )
        ).one()
    assert rows.before == {"invoice_prefix": "INV"}
    assert rows.after["invoice_prefix"] == "FY27"
    assert rows.actor_user_id == seed.owner_a
    await _patch(client, seed, {"invoice_prefix": "INV"})


async def test_invoice_prefix_rules(client: httpx.AsyncClient, seed: Seed) -> None:
    for bad in ("", "IN/V", "WAYTOOLONGPREFIX"):
        r = await _patch(client, seed, {"invoice_prefix": bad})
        assert r.status_code == 422, bad


async def test_prices_mode_locks_once_the_menu_has_items(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    owner = hdr(seed.token(seed.owner_a, Role.OWNER))
    base = f"/v1/outlets/{seed.outlet_a}"
    tax = (
        await client.post(
            f"{base}/tax-classes", json={"name": "Lock 5%", "gst_rate_bp": 500}, headers=owner
        )
    ).json()
    cat = (await client.post(f"{base}/categories", json={"name": "Lock cat"}, headers=owner)).json()
    same = await _patch(client, seed, {"prices_include_tax": True})
    assert same.status_code == 200  # no-op change is fine
    item = await client.post(
        f"{base}/items",
        json={
            "category_id": cat["id"],
            "name": "Lock item",
            "base_price_paise": 10000,
            "tax_class_id": tax["id"],
        },
        headers=owner,
    )
    assert item.status_code == 201
    locked = await _patch(client, seed, {"prices_include_tax": False})
    assert (locked.status_code, locked.json()["code"]) == (409, "prices_mode_locked")
    await client.delete(f"{base}/items/{item.json()['id']}", headers=owner)
    unlocked = await _patch(client, seed, {"prices_include_tax": False})
    assert unlocked.status_code == 200
    await _patch(client, seed, {"prices_include_tax": True})


async def test_owner_of_tenant_a_cannot_touch_tenant_b_settings(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    r = await client.patch(
        f"/v1/outlets/{seed.outlet_b}/settings",
        json={"waiter_confirm_mode": True},
        headers=hdr(seed.token(seed.owner_a, Role.OWNER)),
    )
    assert r.status_code == 403


async def test_idempotency_replays_same_response_and_rejects_reuse_with_new_body(
    client: httpx.AsyncClient, seed: Seed, owner_engine: AsyncEngine
) -> None:
    key = uuid.uuid4()
    owner = hdr(seed.token(seed.owner_a, Role.OWNER), key)
    url = f"/v1/outlets/{seed.outlet_a}/settings"
    first = await client.patch(url, json={"address": "1 MG Road"}, headers=owner)
    replay = await client.patch(url, json={"address": "1 MG Road"}, headers=owner)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    async with owner_engine.connect() as conn:
        audits = await conn.scalar(
            text(
                "SELECT count(*) FROM audit_log WHERE restaurant_id = :r "
                "AND action = 'outlet.settings_updated' AND after = CAST(:a AS jsonb)"
            ),
            {"r": seed.restaurant_a, "a": '{"address": "1 MG Road"}'},
        )
    assert audits == 1  # the replay did not run the handler again

    reuse = await client.patch(url, json={"address": "2 MG Road"}, headers=owner)
    assert (reuse.status_code, reuse.json()["code"]) == (422, "idempotency_key_reused")
