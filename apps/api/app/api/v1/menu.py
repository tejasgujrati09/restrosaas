from __future__ import annotations

import csv
import io
from datetime import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select

from app.api.v1.common import (
    ERRORS,
    Ctx,
    IdempotencyKeyHeader,
    idempotent_write,
    invalid,
    not_found,
)
from app.core.permissions import Capability, assert_can
from app.deps import OutletContext
from app.domains.menu.csv_import import COLUMNS
from app.domains.menu.models import (
    MenuCategory,
    MenuItem,
    MenuItemModifierGroup,
    Modifier,
    ModifierGroup,
)
from app.domains.tenant.models import Outlet, Station, TaxClass

router = APIRouter(prefix="/v1/outlets/{outlet_id}", tags=["menu"])

# --------------------------------------------------------------------- schemas


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TaxClassIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    gst_rate_bp: int = Field(default=0, ge=0, le=10_000)
    liquor_vat: bool = False

    @model_validator(mode="after")
    def _liquor_has_no_gst(self) -> TaxClassIn:
        if self.liquor_vat and self.gst_rate_bp != 0:
            raise ValueError("liquor is taxed by state VAT, not GST; set the GST rate to 0")
        return self


class TaxClassOut(_Out):
    id: UUID
    name: str
    gst_rate_bp: int
    liquor_vat: bool


class StationIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class StationOut(_Out):
    id: UUID
    name: str


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = 0
    visible: bool = True
    available_from: time | None = None
    available_to: time | None = None


class CategoryOut(_Out):
    id: UUID
    name: str
    sort_order: int
    visible: bool
    available_from: time | None
    available_to: time | None


class ModifierIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    price_delta_paise: int = 0


class ModifierOut(_Out):
    id: UUID
    name: str
    price_delta_paise: int


class ModifierGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    min_select: int = Field(default=0, ge=0)
    max_select: int = Field(default=1, ge=1)
    modifiers: list[ModifierIn] = []

    @model_validator(mode="after")
    def _min_le_max(self) -> ModifierGroupIn:
        if self.max_select < self.min_select:
            raise ValueError("max_select must be at least min_select")
        return self


class ModifierGroupOut(BaseModel):
    id: UUID
    name: str
    min_select: int
    max_select: int
    modifiers: list[ModifierOut]


class ItemIn(BaseModel):
    category_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    # Exactly what the owner typed, in the outlet's with-tax / plus-tax mode.
    base_price_paise: int = Field(ge=0)
    tax_class_id: UUID
    station_id: UUID | None = None
    veg_flag: bool = True
    is_liquor: bool = False
    needs_approval: bool = False
    available: bool = True
    image_url: str | None = Field(default=None, max_length=500)
    sort_order: int = 0
    sku: str | None = Field(default=None, max_length=100)
    modifier_group_ids: list[UUID] = []


class ItemOut(BaseModel):
    id: UUID
    category_id: UUID
    name: str
    description: str | None
    base_price_paise: int
    tax_class_id: UUID
    station_id: UUID | None
    veg_flag: bool
    is_liquor: bool
    needs_approval: bool
    available: bool
    image_url: str | None
    sort_order: int
    sku: str | None
    modifier_group_ids: list[UUID]


class AvailabilityIn(BaseModel):
    available: bool


class MenuCategoryOut(CategoryOut):
    items: list[ItemOut]


class MenuOut(BaseModel):
    prices_include_tax: bool
    tax_classes: list[TaxClassOut]
    stations: list[StationOut]
    modifier_groups: list[ModifierGroupOut]
    categories: list[MenuCategoryOut]


# --------------------------------------------------------------------- helpers


async def _owned[M: Any](ctx: OutletContext, model: type[M], row_id: UUID, what: str) -> M:
    row = await ctx.session.get(model, row_id)
    if row is None or getattr(row, "outlet_id", ctx.outlet_id) != ctx.outlet_id:
        raise not_found(what)
    return row


async def _item_out(ctx: OutletContext, item: MenuItem) -> ItemOut:
    groups = await ctx.session.scalars(
        select(MenuItemModifierGroup.group_id).where(MenuItemModifierGroup.item_id == item.id)
    )
    return _to_item_out(item, sorted(groups))


def _to_item_out(item: MenuItem, group_ids: list[UUID]) -> ItemOut:
    return ItemOut(
        id=item.id,
        category_id=item.category_id,
        name=item.name,
        description=item.description,
        base_price_paise=item.base_price_paise,
        tax_class_id=item.tax_class_id,
        station_id=item.station_id,
        veg_flag=item.veg_flag,
        is_liquor=item.is_liquor,
        needs_approval=item.needs_approval,
        available=item.available,
        image_url=item.image_url,
        sort_order=item.sort_order,
        sku=item.sku,
        modifier_group_ids=group_ids,
    )


async def _validate_item(ctx: OutletContext, body: ItemIn) -> None:
    outlet = await ctx.session.get(Outlet, ctx.outlet_id)
    assert outlet is not None
    await _owned(ctx, MenuCategory, body.category_id, "Category")
    tax_class = await _owned(ctx, TaxClass, body.tax_class_id, "Tax class")
    if body.station_id is not None:
        await _owned(ctx, Station, body.station_id, "Station")
    if body.is_liquor != tax_class.liquor_vat:
        raise invalid(
            "tax_class_id",
            "Liquor items need a liquor VAT tax class, and food items need a GST tax class.",
            "liquor_tax_mismatch",
        )
    if body.is_liquor and not outlet.liquor_licensed:
        raise invalid("is_liquor", "This outlet is not marked as liquor licensed.")
    for group_id in set(body.modifier_group_ids):
        await _owned(ctx, ModifierGroup, group_id, "Modifier group")


async def _set_item_groups(ctx: OutletContext, item_id: UUID, group_ids: list[UUID]) -> None:
    await ctx.session.execute(
        delete(MenuItemModifierGroup).where(MenuItemModifierGroup.item_id == item_id)
    )
    for group_id in sorted(set(group_ids)):
        ctx.session.add(
            MenuItemModifierGroup(
                item_id=item_id, group_id=group_id, restaurant_id=ctx.restaurant_id
            )
        )
    await ctx.session.flush()


async def _group_out(ctx: OutletContext, group: ModifierGroup) -> ModifierGroupOut:
    modifiers = await ctx.session.scalars(
        select(Modifier).where(Modifier.group_id == group.id).order_by(Modifier.name)
    )
    return ModifierGroupOut(
        id=group.id,
        name=group.name,
        min_select=group.min_select,
        max_select=group.max_select,
        modifiers=[ModifierOut.model_validate(m) for m in modifiers],
    )


async def load_menu(ctx: OutletContext) -> MenuOut:
    outlet = await ctx.session.get(Outlet, ctx.outlet_id)
    assert outlet is not None
    s = ctx.session
    tax_classes = await s.scalars(
        select(TaxClass).where(TaxClass.outlet_id == ctx.outlet_id).order_by(TaxClass.name)
    )
    stations = await s.scalars(
        select(Station).where(Station.outlet_id == ctx.outlet_id).order_by(Station.name)
    )
    groups = await s.scalars(
        select(ModifierGroup)
        .where(ModifierGroup.outlet_id == ctx.outlet_id)
        .order_by(ModifierGroup.name)
    )
    categories = (
        await s.scalars(
            select(MenuCategory)
            .where(MenuCategory.outlet_id == ctx.outlet_id)
            .order_by(MenuCategory.sort_order, MenuCategory.name)
        )
    ).all()
    items = (
        await s.scalars(
            select(MenuItem)
            .where(MenuItem.outlet_id == ctx.outlet_id)
            .order_by(MenuItem.sort_order, MenuItem.name)
        )
    ).all()
    links = await s.execute(
        select(MenuItemModifierGroup.item_id, MenuItemModifierGroup.group_id).where(
            MenuItemModifierGroup.item_id.in_([i.id for i in items])
        )
    )
    group_ids_by_item: dict[UUID, list[UUID]] = {}
    for item_id, group_id in links:
        group_ids_by_item.setdefault(item_id, []).append(group_id)
    items_by_category: dict[UUID, list[ItemOut]] = {}
    for item in items:
        items_by_category.setdefault(item.category_id, []).append(
            _to_item_out(item, sorted(group_ids_by_item.get(item.id, [])))
        )
    return MenuOut(
        prices_include_tax=outlet.prices_include_tax,
        tax_classes=[TaxClassOut.model_validate(t) for t in tax_classes],
        stations=[StationOut.model_validate(x) for x in stations],
        modifier_groups=[await _group_out(ctx, g) for g in groups],
        categories=[
            MenuCategoryOut(
                **CategoryOut.model_validate(c).model_dump(), items=items_by_category.get(c.id, [])
            )
            for c in categories
        ],
    )


def menu_to_rows(menu: MenuOut) -> list[list[str]]:
    tax = {t.id: t.name for t in menu.tax_classes}
    stations = {s.id: s.name for s in menu.stations}
    groups = {g.id: g.name for g in menu.modifier_groups}
    rows: list[list[str]] = []
    for category in menu.categories:
        for item in category.items:
            rupees, paise = divmod(item.base_price_paise, 100)
            rows.append(
                [
                    category.name,
                    item.name,
                    item.description or "",
                    f"{rupees}.{paise:02d}",
                    tax[item.tax_class_id],
                    "yes" if item.veg_flag else "no",
                    "yes" if item.is_liquor else "no",
                    stations[item.station_id] if item.station_id else "",
                    "yes" if item.available else "no",
                    item.sku or "",
                    ";".join(sorted(groups[g] for g in item.modifier_group_ids)),
                ]
            )
    return rows


# ------------------------------------------------------------------------ menu


@router.get("/menu", responses=ERRORS)
async def get_menu(ctx: Ctx) -> MenuOut:
    assert_can(ctx.actor, Capability.VIEW_MENU, ctx.outlet_id)
    return await load_menu(ctx)


@router.get("/menu/export.csv", responses=ERRORS)
async def export_menu_csv(ctx: Ctx) -> Response:
    """Current menu in the import format; with an empty menu it is the template."""
    assert_can(ctx.actor, Capability.VIEW_MENU, ctx.outlet_id)
    menu = await load_menu(ctx)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    writer.writerows(menu_to_rows(menu))
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="menu.csv"'},
    )


# ------------------------------------------------------------------ tax classes


@router.post("/tax-classes", status_code=201, responses=ERRORS)
async def create_tax_class(ctx: Ctx, key: IdempotencyKeyHeader, body: TaxClassIn) -> TaxClassOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> TaxClassOut:
        row = TaxClass(
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            name=body.name,
            gst_rate_bp=body.gst_rate_bp,
            liquor_vat=body.liquor_vat,
        )
        ctx.session.add(row)
        await ctx.session.flush()
        return TaxClassOut.model_validate(row)

    return await idempotent_write(ctx, key, "POST tax-classes", body, TaxClassOut, produce)


@router.put("/tax-classes/{tax_class_id}", responses=ERRORS)
async def update_tax_class(
    tax_class_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: TaxClassIn
) -> TaxClassOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> TaxClassOut:
        row = await _owned(ctx, TaxClass, tax_class_id, "Tax class")
        row.name, row.gst_rate_bp, row.liquor_vat = body.name, body.gst_rate_bp, body.liquor_vat
        await ctx.session.flush()
        return TaxClassOut.model_validate(row)

    return await idempotent_write(
        ctx, key, f"PUT tax-classes/{tax_class_id}", body, TaxClassOut, produce
    )


@router.delete("/tax-classes/{tax_class_id}", status_code=204, responses=ERRORS)
async def delete_tax_class(tax_class_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> None:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> None:
        await ctx.session.delete(await _owned(ctx, TaxClass, tax_class_id, "Tax class"))
        await ctx.session.flush()

    await idempotent_write(
        ctx, key, f"DELETE tax-classes/{tax_class_id}", None, type(None), produce
    )


# --------------------------------------------------------------------- stations


@router.post("/stations", status_code=201, responses=ERRORS)
async def create_station(ctx: Ctx, key: IdempotencyKeyHeader, body: StationIn) -> StationOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> StationOut:
        row = Station(restaurant_id=ctx.restaurant_id, outlet_id=ctx.outlet_id, name=body.name)
        ctx.session.add(row)
        await ctx.session.flush()
        return StationOut.model_validate(row)

    return await idempotent_write(ctx, key, "POST stations", body, StationOut, produce)


@router.put("/stations/{station_id}", responses=ERRORS)
async def update_station(
    station_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: StationIn
) -> StationOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> StationOut:
        row = await _owned(ctx, Station, station_id, "Station")
        row.name = body.name
        await ctx.session.flush()
        return StationOut.model_validate(row)

    return await idempotent_write(ctx, key, f"PUT stations/{station_id}", body, StationOut, produce)


@router.delete("/stations/{station_id}", status_code=204, responses=ERRORS)
async def delete_station(station_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> None:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> None:
        await ctx.session.delete(await _owned(ctx, Station, station_id, "Station"))
        await ctx.session.flush()

    await idempotent_write(ctx, key, f"DELETE stations/{station_id}", None, type(None), produce)


# ------------------------------------------------------------------- categories


@router.post("/categories", status_code=201, responses=ERRORS)
async def create_category(ctx: Ctx, key: IdempotencyKeyHeader, body: CategoryIn) -> CategoryOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> CategoryOut:
        row = MenuCategory(
            restaurant_id=ctx.restaurant_id, outlet_id=ctx.outlet_id, **body.model_dump()
        )
        ctx.session.add(row)
        await ctx.session.flush()
        return CategoryOut.model_validate(row)

    return await idempotent_write(ctx, key, "POST categories", body, CategoryOut, produce)


@router.put("/categories/{category_id}", responses=ERRORS)
async def update_category(
    category_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: CategoryIn
) -> CategoryOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> CategoryOut:
        row = await _owned(ctx, MenuCategory, category_id, "Category")
        for name, value in body.model_dump().items():
            setattr(row, name, value)
        await ctx.session.flush()
        return CategoryOut.model_validate(row)

    return await idempotent_write(
        ctx, key, f"PUT categories/{category_id}", body, CategoryOut, produce
    )


@router.delete("/categories/{category_id}", status_code=204, responses=ERRORS)
async def delete_category(category_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> None:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> None:
        await ctx.session.delete(await _owned(ctx, MenuCategory, category_id, "Category"))
        await ctx.session.flush()

    await idempotent_write(ctx, key, f"DELETE categories/{category_id}", None, type(None), produce)


# ------------------------------------------------------------------------ items


@router.post("/items", status_code=201, responses=ERRORS)
async def create_item(ctx: Ctx, key: IdempotencyKeyHeader, body: ItemIn) -> ItemOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> ItemOut:
        await _validate_item(ctx, body)
        row = MenuItem(
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            **body.model_dump(exclude={"modifier_group_ids"}),
        )
        ctx.session.add(row)
        await ctx.session.flush()
        await _set_item_groups(ctx, row.id, body.modifier_group_ids)
        return await _item_out(ctx, row)

    return await idempotent_write(ctx, key, "POST items", body, ItemOut, produce)


@router.put("/items/{item_id}", responses=ERRORS)
async def update_item(item_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: ItemIn) -> ItemOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> ItemOut:
        row = await _owned(ctx, MenuItem, item_id, "Item")
        await _validate_item(ctx, body)
        for name, value in body.model_dump(exclude={"modifier_group_ids"}).items():
            setattr(row, name, value)
        await ctx.session.flush()
        await _set_item_groups(ctx, row.id, body.modifier_group_ids)
        return await _item_out(ctx, row)

    return await idempotent_write(ctx, key, f"PUT items/{item_id}", body, ItemOut, produce)


@router.put("/items/{item_id}/availability", responses=ERRORS)
async def set_item_availability(
    item_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: AvailabilityIn
) -> ItemOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_AVAILABILITY, ctx.outlet_id)

    async def produce() -> ItemOut:
        row = await _owned(ctx, MenuItem, item_id, "Item")
        row.available = body.available
        await ctx.session.flush()
        return await _item_out(ctx, row)

    return await idempotent_write(
        ctx, key, f"PUT items/{item_id}/availability", body, ItemOut, produce
    )


@router.delete("/items/{item_id}", status_code=204, responses=ERRORS)
async def delete_item(item_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> None:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> None:
        row = await _owned(ctx, MenuItem, item_id, "Item")
        await ctx.session.execute(
            delete(MenuItemModifierGroup).where(MenuItemModifierGroup.item_id == item_id)
        )
        await ctx.session.delete(row)
        await ctx.session.flush()

    await idempotent_write(ctx, key, f"DELETE items/{item_id}", None, type(None), produce)


# -------------------------------------------------------------- modifier groups


@router.post("/modifier-groups", status_code=201, responses=ERRORS)
async def create_modifier_group(
    ctx: Ctx, key: IdempotencyKeyHeader, body: ModifierGroupIn
) -> ModifierGroupOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> ModifierGroupOut:
        group = ModifierGroup(
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            name=body.name,
            min_select=body.min_select,
            max_select=body.max_select,
        )
        ctx.session.add(group)
        await ctx.session.flush()
        for m in body.modifiers:
            ctx.session.add(
                Modifier(
                    restaurant_id=ctx.restaurant_id,
                    group_id=group.id,
                    name=m.name,
                    price_delta_paise=m.price_delta_paise,
                )
            )
        await ctx.session.flush()
        return await _group_out(ctx, group)

    return await idempotent_write(ctx, key, "POST modifier-groups", body, ModifierGroupOut, produce)


class ModifierGroupPatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    min_select: int = Field(default=0, ge=0)
    max_select: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _min_le_max(self) -> ModifierGroupPatchIn:
        if self.max_select < self.min_select:
            raise ValueError("max_select must be at least min_select")
        return self


@router.put("/modifier-groups/{group_id}", responses=ERRORS)
async def update_modifier_group(
    group_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: ModifierGroupPatchIn
) -> ModifierGroupOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> ModifierGroupOut:
        group = await _owned(ctx, ModifierGroup, group_id, "Modifier group")
        group.name, group.min_select, group.max_select = body.name, body.min_select, body.max_select
        await ctx.session.flush()
        return await _group_out(ctx, group)

    return await idempotent_write(
        ctx, key, f"PUT modifier-groups/{group_id}", body, ModifierGroupOut, produce
    )


@router.delete("/modifier-groups/{group_id}", status_code=204, responses=ERRORS)
async def delete_modifier_group(group_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> None:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> None:
        group = await _owned(ctx, ModifierGroup, group_id, "Modifier group")
        await ctx.session.execute(delete(Modifier).where(Modifier.group_id == group_id))
        await ctx.session.delete(group)
        await ctx.session.flush()

    await idempotent_write(
        ctx, key, f"DELETE modifier-groups/{group_id}", None, type(None), produce
    )


@router.post("/modifier-groups/{group_id}/modifiers", status_code=201, responses=ERRORS)
async def create_modifier(
    group_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: ModifierIn
) -> ModifierOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> ModifierOut:
        await _owned(ctx, ModifierGroup, group_id, "Modifier group")
        row = Modifier(
            restaurant_id=ctx.restaurant_id,
            group_id=group_id,
            name=body.name,
            price_delta_paise=body.price_delta_paise,
        )
        ctx.session.add(row)
        await ctx.session.flush()
        return ModifierOut.model_validate(row)

    return await idempotent_write(
        ctx, key, f"POST modifier-groups/{group_id}/modifiers", body, ModifierOut, produce
    )


async def _modifier(ctx: OutletContext, group_id: UUID, modifier_id: UUID) -> Modifier:
    await _owned(ctx, ModifierGroup, group_id, "Modifier group")
    row = await ctx.session.get(Modifier, modifier_id)
    if row is None or row.group_id != group_id:
        raise not_found("Modifier")
    return row


@router.put("/modifier-groups/{group_id}/modifiers/{modifier_id}", responses=ERRORS)
async def update_modifier(
    group_id: UUID, modifier_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: ModifierIn
) -> ModifierOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> ModifierOut:
        row = await _modifier(ctx, group_id, modifier_id)
        row.name, row.price_delta_paise = body.name, body.price_delta_paise
        await ctx.session.flush()
        return ModifierOut.model_validate(row)

    return await idempotent_write(
        ctx, key, f"PUT modifiers/{modifier_id}", body, ModifierOut, produce
    )


@router.delete(
    "/modifier-groups/{group_id}/modifiers/{modifier_id}", status_code=204, responses=ERRORS
)
async def delete_modifier(
    group_id: UUID, modifier_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader
) -> None:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> None:
        await ctx.session.delete(await _modifier(ctx, group_id, modifier_id))
        await ctx.session.flush()

    await idempotent_write(ctx, key, f"DELETE modifiers/{modifier_id}", None, type(None), produce)
