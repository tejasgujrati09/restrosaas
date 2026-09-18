from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.v1.common import ERRORS, Ctx, IdempotencyKeyHeader, idempotent_write
from app.api.v1.menu import load_menu
from app.audit import audit
from app.core.permissions import Capability, assert_can
from app.deps import OutletContext
from app.domains.menu.csv_import import (
    ExistingItem,
    ImportContext,
    MenuDiff,
    ParsedRow,
    diff_menu,
    parse_menu_csv,
)
from app.domains.menu.models import MenuCategory, MenuItem, MenuItemModifierGroup, ModifierGroup
from app.domains.tenant.models import Outlet, Station, TaxClass
from app.errors import ApiError

router = APIRouter(prefix="/v1/outlets/{outlet_id}/menu/import", tags=["menu-import"])

MAX_BYTES = 1_000_000


class RowErrorOut(BaseModel):
    row: int
    column: str | None
    message: str


class ItemAddedOut(BaseModel):
    category: str
    item: str
    price_paise: int


class ItemChangeOut(BaseModel):
    category: str
    item: str
    changes: dict[str, tuple[Any, Any]]


class ImportPreviewOut(BaseModel):
    errors: list[RowErrorOut]
    new_categories: list[str]
    added: list[ItemAddedOut]
    changed: list[ItemChangeOut]
    unchanged: int
    not_in_file: list[tuple[str, str]]
    # Present only when the file is valid; pass it back to /apply.
    diff_hash: str | None


class ImportApplyOut(BaseModel):
    categories_added: int
    items_added: int
    items_updated: int


async def _read_csv(request: Request) -> str:
    body = await request.body()
    if len(body) > MAX_BYTES:
        raise ApiError(413, "file_too_large", "The file is too large (1 MB limit).")
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApiError(422, "not_utf8", "Save the file as CSV (UTF-8) and try again.") from exc


async def _analyse(
    ctx: OutletContext, text: str
) -> tuple[list[ParsedRow], MenuDiff | None, list[Any]]:
    outlet = await ctx.session.get(Outlet, ctx.outlet_id)
    assert outlet is not None
    menu = await load_menu(ctx)
    import_ctx = ImportContext(
        tax_classes={t.name.lower(): (t.name, t.liquor_vat) for t in menu.tax_classes},
        stations={s.name.lower(): s.name for s in menu.stations},
        modifier_groups={g.name.lower(): g.name for g in menu.modifier_groups},
        liquor_licensed=outlet.liquor_licensed,
    )
    parsed = parse_menu_csv(text, import_ctx)
    if parsed.errors:
        return [], None, list(parsed.errors)
    tax = {t.id: t.name for t in menu.tax_classes}
    stations = {s.id: s.name for s in menu.stations}
    groups = {g.id: g.name for g in menu.modifier_groups}
    existing = [
        ExistingItem(
            category=c.name,
            item=i.name,
            description=i.description,
            price_paise=i.base_price_paise,
            tax_class=tax[i.tax_class_id],
            veg=i.veg_flag,
            is_liquor=i.is_liquor,
            station=stations[i.station_id] if i.station_id else None,
            available=i.available,
            sku=i.sku,
            modifier_groups=tuple(sorted(groups[g] for g in i.modifier_group_ids)),
        )
        for c in menu.categories
        for i in c.items
    ]
    diff = diff_menu(parsed.rows, existing, [c.name for c in menu.categories])
    return parsed.rows, diff, []


def _preview(diff: MenuDiff | None, errors: list[Any]) -> ImportPreviewOut:
    if diff is None:
        return ImportPreviewOut(
            errors=[RowErrorOut(row=e.row, column=e.column, message=e.message) for e in errors],
            new_categories=[],
            added=[],
            changed=[],
            unchanged=0,
            not_in_file=[],
            diff_hash=None,
        )
    return ImportPreviewOut(
        errors=[],
        new_categories=diff.new_categories,
        added=[
            ItemAddedOut(category=r.category, item=r.item, price_paise=r.price_paise)
            for r in diff.added
        ],
        changed=[
            ItemChangeOut(category=c.category, item=c.item, changes=c.changes) for c in diff.changed
        ],
        unchanged=diff.unchanged,
        not_in_file=diff.not_in_file,
        diff_hash=diff.digest(),
    )


@router.post("/preview", responses=ERRORS)
async def preview_import(ctx: Ctx, request: Request) -> ImportPreviewOut:
    """Body is the raw CSV. Nothing is written."""
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)
    _, diff, errors = await _analyse(ctx, await _read_csv(request))
    return _preview(diff, errors)


@router.post("/apply", responses=ERRORS)
async def apply_import(
    ctx: Ctx,
    request: Request,
    key: IdempotencyKeyHeader,
    diff_hash: Annotated[str, Query(min_length=64, max_length=64)],
) -> ImportApplyOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)
    text = await _read_csv(request)

    async def produce() -> ImportApplyOut:
        rows, diff, errors = await _analyse(ctx, text)
        if diff is None:
            raise ApiError(
                409,
                "import_has_errors",
                "Fix the errors in the file first.",
                {"errors": len(errors)},
            )
        if diff.digest() != diff_hash:
            raise ApiError(
                409, "menu_changed", "The menu changed since the preview. Preview the file again."
            )
        result = await _apply(ctx, diff)
        audit(ctx, "menu.import_applied", "outlet", ctx.outlet_id, None, result.model_dump())
        return result

    return await idempotent_write(
        ctx,
        key,
        "POST menu/import/apply",
        {"diff_hash": diff_hash, "csv": text},
        ImportApplyOut,
        produce,
    )


async def _apply(ctx: OutletContext, diff: MenuDiff) -> ImportApplyOut:
    s = ctx.session
    next_order = (
        await s.scalar(
            select(func.coalesce(func.max(MenuCategory.sort_order), -1)).where(
                MenuCategory.outlet_id == ctx.outlet_id
            )
        )
    ) or -1
    for name in diff.new_categories:
        next_order += 1
        s.add(
            MenuCategory(
                restaurant_id=ctx.restaurant_id,
                outlet_id=ctx.outlet_id,
                name=name,
                sort_order=next_order,
            )
        )
    await s.flush()

    categories = {
        c.name.lower(): c
        for c in await s.scalars(
            select(MenuCategory).where(MenuCategory.outlet_id == ctx.outlet_id)
        )
    }
    tax = {
        t.name: t.id
        for t in await s.scalars(select(TaxClass).where(TaxClass.outlet_id == ctx.outlet_id))
    }
    stations = {
        x.name: x.id
        for x in await s.scalars(select(Station).where(Station.outlet_id == ctx.outlet_id))
    }
    groups = {
        g.name: g.id
        for g in await s.scalars(
            select(ModifierGroup).where(ModifierGroup.outlet_id == ctx.outlet_id)
        )
    }

    async def set_groups(item_id: Any, names: tuple[str, ...]) -> None:
        from sqlalchemy import delete

        await s.execute(
            delete(MenuItemModifierGroup).where(MenuItemModifierGroup.item_id == item_id)
        )
        for name in names:
            s.add(
                MenuItemModifierGroup(
                    item_id=item_id, group_id=groups[name], restaurant_id=ctx.restaurant_id
                )
            )

    for row in diff.added:
        new_item = MenuItem(
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            category_id=categories[row.category.lower()].id,
            name=row.item,
            description=row.description,
            base_price_paise=row.price_paise,
            tax_class_id=tax[row.tax_class],
            station_id=stations[row.station] if row.station else None,
            veg_flag=row.veg,
            is_liquor=row.is_liquor,
            available=row.available,
            sku=row.sku,
        )
        s.add(new_item)
        await s.flush()
        await set_groups(new_item.id, row.modifier_groups)

    for change in diff.changed:
        existing = await s.scalar(
            select(MenuItem).where(
                MenuItem.category_id == categories[change.category.lower()].id,
                func.lower(MenuItem.name) == change.item.lower(),
            )
        )
        assert existing is not None
        for field_name, (_, new) in change.changes.items():
            if field_name == "price_paise":
                existing.base_price_paise = new
            elif field_name == "tax_class":
                existing.tax_class_id = tax[new]
            elif field_name == "station":
                existing.station_id = stations[new] if new else None
            elif field_name == "modifier_groups":
                await set_groups(existing.id, new)
            else:
                setattr(existing, "veg_flag" if field_name == "veg" else field_name, new)
        await s.flush()
    await s.flush()
    return ImportApplyOut(
        categories_added=len(diff.new_categories),
        items_added=len(diff.added),
        items_updated=len(diff.changed),
    )
