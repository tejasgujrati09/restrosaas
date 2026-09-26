from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.v1 import menu_imports
from app.config import settings
from app.core.permissions import Role
from app.domains.menu.extract import jobs, pipeline
from app.storage import MemoryStorage, set_storage
from tests.api.helpers import Menu, build_menu, cleanup_menu
from tests.conftest import Seed, hdr
from tests.menu_extract_fakes import FakeProvider, fatal, item, page, transient


def jpeg(color: str = "white") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (300, 200), color).save(out, "JPEG")
    return out.getvalue()


def scanned_pdf(pages: int = 1) -> bytes:
    out = io.BytesIO()
    images = [Image.new("RGB", (300, 400), "white") for _ in range(pages)]
    images[0].save(out, "PDF", save_all=True, append_images=images[1:])
    return out.getvalue()


class Wiring:
    def __init__(self, seed: Seed, storage: MemoryStorage) -> None:
        self.seed = seed
        self.storage = storage
        self.queued: list[uuid.UUID] = []

    async def run(self, import_id: str, provider: FakeProvider) -> str:
        return await pipeline.run_extraction(
            self.seed.restaurant_a, self.seed.outlet_a, uuid.UUID(import_id), provider, self.storage
        )


@pytest.fixture
async def wiring(seed: Seed, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Wiring]:
    storage = MemoryStorage()
    set_storage(storage)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    async def no_wait(_: float) -> None:
        return None

    pipeline.set_sleep(no_wait)
    w = Wiring(seed, storage)
    jobs.set_dispatcher(lambda restaurant, outlet, import_id: w.queued.append(import_id))
    yield w
    jobs.set_dispatcher(None)
    pipeline.set_sleep(None)
    set_storage(None)


@pytest.fixture
async def menu(
    client: httpx.AsyncClient, seed: Seed, owner_engine: AsyncEngine
) -> AsyncIterator[Menu]:
    built = await build_menu(client, seed, "M")
    yield built
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM menu_import WHERE outlet_id = :o"), {"o": seed.outlet_a}
        )
    await cleanup_menu(client, built)


def files(*items: tuple[str, bytes]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (name, data, "application/octet-stream")) for name, data in items]


async def upload(
    client: httpx.AsyncClient, menu: Menu, *items: tuple[str, bytes], key: uuid.UUID | None = None
) -> httpx.Response:
    headers = dict(menu.owner)
    if key:
        headers["Idempotency-Key"] = str(key)
    return await client.post(f"{menu.base}/menu/imports", files=files(*items), headers=headers)


async def upload_ok(client: httpx.AsyncClient, menu: Menu, *items: tuple[str, bytes]) -> str:
    r = await upload(client, menu, *items or (("menu.jpg", jpeg()),))
    assert r.status_code == 202, r.text
    return str(r.json()["id"])


async def review(client: httpx.AsyncClient, menu: Menu, import_id: str) -> dict[str, Any]:
    r = await client.get(f"{menu.base}/menu/imports/{import_id}/preview", headers=menu.owner)
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


async def confirm(
    client: httpx.AsyncClient,
    menu: Menu,
    import_id: str,
    diff_hash: str,
    key: uuid.UUID | None = None,
) -> httpx.Response:
    headers = dict(menu.owner)
    if key:
        headers["Idempotency-Key"] = str(key)
    return await client.post(
        f"{menu.base}/menu/imports/{import_id}/confirm?diff_hash={diff_hash}", headers=headers
    )


TWO_PAGES = {
    1: page(("M Starters", [item("M Spring Roll", "150"), item("M Soup", None)])),
    2: page(("M Mains", [item("M Dal Makhani", options=[("Half", "120"), ("Full", "220")])])),
}


async def menu_names(client: httpx.AsyncClient, menu: Menu) -> set[str]:
    tree = (await client.get(f"{menu.base}/menu", headers=menu.owner)).json()
    return {i["name"] for c in tree["categories"] for i in c["items"]}


# ---- the whole flow -----------------------------------------------------------------------


async def test_upload_extract_review_edit_confirm(
    client: httpx.AsyncClient, seed: Seed, menu: Menu, wiring: Wiring
) -> None:
    import_id = await upload_ok(client, menu, ("p1.jpg", jpeg()), ("p2.jpg", jpeg("gray")))
    assert wiring.queued == [uuid.UUID(import_id)]
    queued = (await client.get(f"{menu.base}/menu/imports/{import_id}", headers=menu.owner)).json()
    assert (queued["status"], queued["pages_total"]) == ("queued", 2)
    assert (
        await client.get(f"{menu.base}/menu/imports/{import_id}/preview", headers=menu.owner)
    ).status_code == 409

    provider = FakeProvider(TWO_PAGES)
    assert await wiring.run(import_id, provider) == "ready"
    assert provider.calls == [1, 2]  # upload order kept
    assert wiring.storage.objects == {}  # originals are deleted once read

    job = (await client.get(f"{menu.base}/menu/imports/{import_id}", headers=menu.owner)).json()
    assert job["status"] == "ready" and job["pages_done"] == 2
    assert job["usage"]["requests"] == 2 and job["usage"]["prompt_tokens"] == 2000
    assert job["usage"]["estimated_cost_usd"] > 0

    data = await review(client, menu, import_id)
    rows = {r["item"]: r for r in data["rows"]}
    assert set(rows) == {"M Spring Roll", "M Soup", "M Dal Makhani (Half)", "M Dal Makhani (Full)"}
    assert data["defaults"]["food_tax_class"] == "M Food 5%"  # the only food class
    assert rows["M Soup"]["errors"] and "Price" in rows["M Soup"]["errors"][0]
    assert data["diff"] is None  # blocked until the price is fixed

    # Confirming with errors writes nothing.
    r = await confirm(client, menu, import_id, "0" * 64)
    assert (r.status_code, r.json()["code"]) == (409, "import_has_errors")
    assert "M Spring Roll" not in await menu_names(client, menu)

    edited = [{**row, "price": "90"} if row["item"] == "M Soup" else row for row in data["rows"]]
    r = await client.put(
        f"{menu.base}/menu/imports/{import_id}",
        json={"rows": edited, "defaults": data["defaults"]},
        headers=menu.owner,
    )
    assert r.status_code == 200
    fixed = r.json()
    assert all(not row["errors"] for row in fixed["rows"])
    diff = fixed["diff"]
    assert len(diff["added"]) == 4 and diff["new_categories"] == ["M Mains"]

    csv = (await client.get(f"{menu.base}/menu/imports/{import_id}/csv", headers=menu.owner)).text
    assert csv.splitlines()[0].startswith("category,item,description,price,tax_class")
    assert "M Soup,,90,M Food 5%" in csv

    key = uuid.uuid4()
    done = await confirm(client, menu, import_id, diff["diff_hash"], key)
    assert done.status_code == 200 and done.json()["items_added"] == 4
    assert {"M Spring Roll", "M Soup", "M Dal Makhani (Full)"} <= await menu_names(client, menu)

    replay = await confirm(client, menu, import_id, diff["diff_hash"], key)
    assert replay.json() == done.json()
    again = await confirm(client, menu, import_id, diff["diff_hash"], uuid.uuid4())
    assert (again.status_code, again.json()["code"]) == (409, "import_wrong_state")
    put = await client.put(
        f"{menu.base}/menu/imports/{import_id}",
        json={"rows": edited, "defaults": data["defaults"]},
        headers=menu.owner,
    )
    assert put.status_code == 409


async def test_existing_items_are_updated_skipped_or_flagged_as_similar(
    client: httpx.AsyncClient, seed: Seed, menu: Menu, wiring: Wiring
) -> None:
    script = {
        1: page(
            (
                "m starters",
                [
                    item("m paneer tikka", "350"),  # same item, new price
                    item("M Paneer Tikkaa", "400"),  # near-duplicate spelling
                    item("M Fresh Item", "80"),
                ],
            )
        )
    }
    import_id = await upload_ok(client, menu)
    await wiring.run(import_id, FakeProvider(script))
    data = await review(client, menu, import_id)
    assert data["matches_existing"] == 1 and data["similar_existing"] == 1
    similar = next(r for r in data["rows"] if r["item"] == "M Paneer Tikkaa")
    assert similar["similar_to"] == "M Paneer Tikka"
    assert len(data["diff"]["changed"]) == 1

    skipped = [{**r, "skip": r["item"] == "M Paneer Tikkaa"} for r in data["rows"]]
    r = await client.put(
        f"{menu.base}/menu/imports/{import_id}",
        json={"rows": skipped, "defaults": data["defaults"]},
        headers=menu.owner,
    )
    diff = r.json()["diff"]
    assert (await confirm(client, menu, import_id, diff["diff_hash"])).json() == {
        "categories_added": 0,
        "items_added": 1,
        "items_updated": 1,
    }
    names = await menu_names(client, menu)
    assert "M Fresh Item" in names and "M Paneer Tikkaa" not in names


# ---- failures and retry -------------------------------------------------------------------


async def test_failed_page_is_retried_alone_and_the_job_can_be_retried(
    client: httpx.AsyncClient, seed: Seed, menu: Menu, wiring: Wiring
) -> None:
    import_id = await upload_ok(client, menu, ("a.jpg", jpeg()), ("b.jpg", jpeg("gray")))
    script: dict[int, Any] = {**TWO_PAGES, 2: [transient(), transient(), transient()]}
    provider = FakeProvider(script)
    assert await wiring.run(import_id, provider) == "failed"
    assert provider.calls == [1, 2, 2, 2]  # three attempts on the failing page
    job = (await client.get(f"{menu.base}/menu/imports/{import_id}", headers=menu.owner)).json()
    assert job["failed_pages"] == [2] and "page 2" in job["error"] and job["usage"]["retries"] == 2
    assert len(wiring.storage.objects) == 2  # kept so it can be retried

    script[2] = [TWO_PAGES[2]]
    r = await client.post(f"{menu.base}/menu/imports/{import_id}/retry", headers=menu.owner)
    assert r.status_code == 202 and wiring.queued[-1] == uuid.UUID(import_id)
    assert await wiring.run(import_id, provider) == "ready"
    assert provider.calls == [1, 2, 2, 2, 2]  # page 1 was not sent again
    assert len((await review(client, menu, import_id))["rows"]) == 4

    again = await client.post(f"{menu.base}/menu/imports/{import_id}/retry", headers=menu.owner)
    assert (again.status_code, again.json()["code"]) == (409, "import_wrong_state")


async def test_non_retryable_and_malformed_answers_fail_the_page(
    client: httpx.AsyncClient, seed: Seed, menu: Menu, wiring: Wiring
) -> None:
    import_id = await upload_ok(client, menu)
    provider = FakeProvider({1: fatal()})
    assert await wiring.run(import_id, provider) == "failed"
    assert provider.calls == [1]

    r = await client.post(f"{menu.base}/menu/imports/{import_id}/retry", headers=menu.owner)
    assert r.status_code == 202
    bad = FakeProvider({1: [{"categories": "not a list"}] * 3})
    assert await wiring.run(import_id, bad) == "failed"
    assert bad.calls == [1, 1, 1]
    job = (await client.get(f"{menu.base}/menu/imports/{import_id}", headers=menu.owner)).json()
    assert job["status"] == "failed" and job["failed_pages"] == [1]


async def test_a_file_with_no_menu_in_it_fails_with_a_plain_message(
    client: httpx.AsyncClient, seed: Seed, menu: Menu, wiring: Wiring
) -> None:
    import_id = await upload_ok(client, menu)
    assert await wiring.run(import_id, FakeProvider({1: page(is_menu=False)})) == "failed"
    job = (await client.get(f"{menu.base}/menu/imports/{import_id}", headers=menu.owner)).json()
    assert "could not find a menu" in job["error"]


async def test_unexpected_errors_and_lost_files_end_as_failed_not_stuck(
    client: httpx.AsyncClient, seed: Seed, menu: Menu, wiring: Wiring
) -> None:
    class Exploding(FakeProvider):
        async def extract_page(self, page):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    import_id = await upload_ok(client, menu)
    assert await wiring.run(import_id, Exploding({})) == "failed"

    second = await upload_ok(client, menu)
    wiring.storage.objects.clear()
    assert await wiring.run(second, FakeProvider({})) == "failed"
    job = (await client.get(f"{menu.base}/menu/imports/{second}", headers=menu.owner)).json()
    assert "could not be loaded" in job["error"]


async def test_a_job_is_processed_once_even_if_the_message_arrives_twice(
    client: httpx.AsyncClient, seed: Seed, menu: Menu, wiring: Wiring
) -> None:
    import_id = await upload_ok(client, menu)
    provider = FakeProvider({1: page(("M A", [item("M One", "10")]))})
    assert await wiring.run(import_id, provider) == "ready"
    assert await wiring.run(import_id, provider) == "skipped"
    assert provider.calls == [1]


async def test_too_many_pages_found_by_the_worker_fail_the_job(
    client: httpx.AsyncClient,
    seed: Seed,
    menu: Menu,
    wiring: Wiring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import_id = await upload_ok(client, menu, ("scan.pdf", scanned_pdf(3)))
    monkeypatch.setattr(settings, "menu_extraction_max_pages", 2)
    assert await wiring.run(import_id, FakeProvider({})) == "failed"


async def test_pdf_pages_of_a_scanned_pdf_go_to_the_model_as_images(
    client: httpx.AsyncClient, seed: Seed, menu: Menu, wiring: Wiring
) -> None:
    import_id = await upload_ok(client, menu, ("scan.pdf", scanned_pdf(2)))
    provider = FakeProvider(
        {1: page(("M A", [item("M One", "10")])), 2: page(("M A", [item("M Two", "20")]))}
    )
    assert await wiring.run(import_id, provider) == "ready"
    assert all(p.image is not None and p.text is None for p in provider.inputs.values())


# ---- upload validation --------------------------------------------------------------------


async def test_upload_rejects_bad_files_with_clear_errors(
    client: httpx.AsyncClient,
    seed: Seed,
    menu: Menu,
    wiring: Wiring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = await upload(client, menu, ("notes.txt", b"hello"))
    assert (r.status_code, r.json()["code"]) == (422, "unsupported_file")
    assert "notes.txt" in r.json()["message"]
    r = await upload(client, menu, ("bad.pdf", b"%PDF-1.4 nonsense"))
    assert (r.status_code, r.json()["code"]) == (422, "unsupported_file")
    r = await upload(client, menu, ("empty.jpg", b""))
    assert r.json()["code"] == "empty_file"
    no_files = await client.post(f"{menu.base}/menu/imports", headers=menu.owner)
    assert no_files.status_code == 422

    monkeypatch.setattr(settings, "menu_extraction_max_file_bytes", 100)
    r = await upload(client, menu, ("big.jpg", jpeg()))
    assert (r.status_code, r.json()["code"]) == (413, "file_too_large")
    monkeypatch.setattr(settings, "menu_extraction_max_file_bytes", 15_000_000)

    monkeypatch.setattr(settings, "menu_extraction_max_files", 1)
    r = await upload(client, menu, ("a.jpg", jpeg()), ("b.jpg", jpeg()))
    assert r.json()["code"] == "too_many_files"
    monkeypatch.setattr(settings, "menu_extraction_max_files", 20)

    monkeypatch.setattr(settings, "menu_extraction_max_pages", 2)
    r = await upload(client, menu, ("scan.pdf", scanned_pdf(3)))
    assert r.json()["code"] == "too_many_pages"
    assert wiring.storage.objects == {} and wiring.queued == []


async def test_upload_needs_a_configured_provider_and_working_storage(
    client: httpx.AsyncClient,
    seed: Seed,
    menu: Menu,
    wiring: Wiring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenStorage(MemoryStorage):
        async def put(self, key: str, data: bytes, content_type: str) -> None:
            raise OSError("down")

    set_storage(BrokenStorage())
    r = await upload(client, menu, ("a.jpg", jpeg()))
    assert (r.status_code, r.json()["code"]) == (503, "storage_unavailable")
    set_storage(wiring.storage)

    monkeypatch.setattr(settings, "openai_api_key", None)
    r = await upload(client, menu, ("a.jpg", jpeg()))
    assert (r.status_code, r.json()["code"]) == (503, "menu_extraction_not_configured")


async def test_upload_is_idempotent(
    client: httpx.AsyncClient, seed: Seed, menu: Menu, wiring: Wiring
) -> None:
    key = uuid.uuid4()
    first = await upload(client, menu, ("a.jpg", jpeg()), key=key)
    second = await upload(client, menu, ("a.jpg", jpeg()), key=key)
    assert first.json()["id"] == second.json()["id"] and len(wiring.queued) == 1
    other = await upload(client, menu, ("a.jpg", jpeg("gray")), key=key)
    assert other.json()["code"] == "idempotency_key_reused"


async def test_old_failed_uploads_are_cleaned_up_on_the_next_upload(
    client: httpx.AsyncClient,
    seed: Seed,
    menu: Menu,
    wiring: Wiring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = await upload_ok(client, menu)
    await wiring.run(old, FakeProvider({1: fatal()}))
    assert len(wiring.storage.objects) == 1
    monkeypatch.setattr(menu_imports, "_EXPIRE_AFTER_HOURS", -1)
    await upload_ok(client, menu)
    assert len(wiring.storage.objects) == 1  # the old one went, the new one arrived
    retry = await client.post(f"{menu.base}/menu/imports/{old}/retry", headers=menu.owner)
    assert (retry.status_code, retry.json()["code"]) == (409, "files_expired")


# ---- who may do this ----------------------------------------------------------------------


async def test_only_the_owner_can_import_and_tenants_are_isolated(
    client: httpx.AsyncClient, seed: Seed, menu: Menu, wiring: Wiring
) -> None:
    for role, user in ((Role.MANAGER, seed.manager_a), (Role.WAITER, seed.waiter_a)):
        r = await client.post(
            f"{menu.base}/menu/imports",
            files=files(("a.jpg", jpeg())),
            headers=hdr(seed.token(user, role)),
        )
        assert r.status_code == 403
    assert wiring.storage.objects == {}

    import_id = await upload_ok(client, menu)
    await wiring.run(import_id, FakeProvider({1: page(("M A", [item("M One", "10")]))}))
    manager = hdr(seed.token(seed.manager_a, Role.MANAGER))
    for path in ("", "/preview", "/csv"):
        r = await client.get(f"{menu.base}/menu/imports/{import_id}{path}", headers=manager)
        assert r.status_code == 403

    owner_b = hdr(seed.token(seed.owner_b, Role.OWNER, tenant="b"))
    base_b = f"/v1/outlets/{seed.outlet_b}/menu/imports/{import_id}"
    assert (await client.get(base_b, headers=owner_b)).status_code == 404
    assert (await client.get(base_b + "/preview", headers=owner_b)).status_code == 404
    cross = await client.get(f"{menu.base}/menu/imports/{import_id}", headers=owner_b)
    assert cross.status_code == 403
    missing = await client.get(f"{menu.base}/menu/imports/{uuid.uuid4()}", headers=menu.owner)
    assert missing.status_code == 404
