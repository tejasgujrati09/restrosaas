from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.common import ERRORS, Ctx, IdempotencyKeyHeader, idempotent_write, not_found
from app.api.v1.menu import load_menu
from app.audit import audit
from app.core.permissions import Capability, assert_can, can
from app.deps import OutletContext
from app.domains.tenant.models import DiningTable, Outlet, Restaurant
from app.pdf import menu_html, qr_sheet_html, render_pdf
from app.qr import new_qr_token, qr_svg, qr_url

router = APIRouter(prefix="/v1/outlets/{outlet_id}", tags=["tables"])


class TableIn(BaseModel):
    label: str = Field(min_length=1, max_length=20)
    zone: str = Field(default="floor", min_length=1, max_length=50)
    seats: int = Field(default=2, ge=1, le=100)
    requires_waiter_confirm: bool = False
    active: bool = True


class BulkTablesIn(BaseModel):
    zone: str = Field(default="floor", min_length=1, max_length=50)
    labels: list[Annotated[str, Field(min_length=1, max_length=20)]] = Field(
        min_length=1, max_length=200
    )
    seats: int = Field(default=2, ge=1, le=100)


class TableOut(BaseModel):
    id: UUID
    label: str
    zone: str
    seats: int
    requires_waiter_confirm: bool
    active: bool
    # Only for roles that may print QRs; a table's QR link opens orders on it.
    qr_url: str | None


def _out(ctx: OutletContext, row: DiningTable) -> TableOut:
    may_see_qr = can(ctx.actor, Capability.GENERATE_TABLE_QRS, ctx.outlet_id)
    return TableOut(
        id=row.id,
        label=row.label,
        zone=row.zone,
        seats=row.seats,
        requires_waiter_confirm=row.requires_waiter_confirm,
        active=row.active,
        qr_url=qr_url(row.qr_token) if may_see_qr else None,
    )


async def _owned_table(ctx: OutletContext, table_id: UUID) -> DiningTable:
    row = await ctx.session.get(DiningTable, table_id)
    if row is None or row.outlet_id != ctx.outlet_id:
        raise not_found("Table")
    return row


@router.get("/tables", responses=ERRORS)
async def list_tables(ctx: Ctx) -> list[TableOut]:
    assert_can(ctx.actor, Capability.VIEW_TABLES_AND_TABS, ctx.outlet_id)
    rows = await ctx.session.scalars(
        select(DiningTable)
        .where(DiningTable.outlet_id == ctx.outlet_id)
        .order_by(DiningTable.zone, DiningTable.label)
    )
    return [_out(ctx, t) for t in rows]


@router.post("/tables", status_code=201, responses=ERRORS)
async def create_table(ctx: Ctx, key: IdempotencyKeyHeader, body: TableIn) -> TableOut:
    assert_can(ctx.actor, Capability.GENERATE_TABLE_QRS, ctx.outlet_id)

    async def produce() -> TableOut:
        row = DiningTable(
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            qr_token=new_qr_token(),
            **body.model_dump(),
        )
        ctx.session.add(row)
        await ctx.session.flush()
        return _out(ctx, row)

    return await idempotent_write(ctx, key, "POST tables", body, TableOut, produce)


@router.post("/tables/bulk", status_code=201, responses=ERRORS)
async def create_tables_bulk(
    ctx: Ctx, key: IdempotencyKeyHeader, body: BulkTablesIn
) -> list[TableOut]:
    assert_can(ctx.actor, Capability.GENERATE_TABLE_QRS, ctx.outlet_id)

    async def produce() -> list[TableOut]:
        rows = [
            DiningTable(
                restaurant_id=ctx.restaurant_id,
                outlet_id=ctx.outlet_id,
                label=label,
                zone=body.zone,
                seats=body.seats,
                qr_token=new_qr_token(),
            )
            for label in body.labels
        ]
        ctx.session.add_all(rows)
        await ctx.session.flush()
        return [_out(ctx, r) for r in rows]

    return await idempotent_write(ctx, key, "POST tables/bulk", body, list[TableOut], produce)


@router.put("/tables/{table_id}", responses=ERRORS)
async def update_table(
    table_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: TableIn
) -> TableOut:
    assert_can(ctx.actor, Capability.GENERATE_TABLE_QRS, ctx.outlet_id)

    async def produce() -> TableOut:
        row = await _owned_table(ctx, table_id)
        for name, value in body.model_dump().items():
            setattr(row, name, value)
        await ctx.session.flush()
        return _out(ctx, row)

    return await idempotent_write(ctx, key, f"PUT tables/{table_id}", body, TableOut, produce)


@router.delete("/tables/{table_id}", status_code=204, responses=ERRORS)
async def delete_table(table_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> None:
    assert_can(ctx.actor, Capability.GENERATE_TABLE_QRS, ctx.outlet_id)

    async def produce() -> None:
        await ctx.session.delete(await _owned_table(ctx, table_id))
        await ctx.session.flush()

    await idempotent_write(ctx, key, f"DELETE tables/{table_id}", None, type(None), produce)


@router.post("/tables/{table_id}/rotate-qr", responses=ERRORS)
async def rotate_qr(table_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> TableOut:
    """Invalidates every printed copy of this table's QR."""
    assert_can(ctx.actor, Capability.GENERATE_TABLE_QRS, ctx.outlet_id)

    async def produce() -> TableOut:
        row = await _owned_table(ctx, table_id)
        row.qr_token = new_qr_token()
        await ctx.session.flush()
        audit(ctx, "table.qr_rotated", "dining_table", row.id)
        return _out(ctx, row)

    return await idempotent_write(
        ctx, key, f"POST tables/{table_id}/rotate-qr", None, TableOut, produce
    )


@router.get("/tables/qr-sheet.pdf", responses=ERRORS)
async def qr_sheet(ctx: Ctx, zone: Annotated[str | None, Query(max_length=50)] = None) -> Response:
    """One page per zone, one card per active table."""
    assert_can(ctx.actor, Capability.GENERATE_TABLE_QRS, ctx.outlet_id)
    restaurant = await ctx.session.get(Restaurant, ctx.restaurant_id)
    assert restaurant is not None
    query = select(DiningTable).where(
        DiningTable.outlet_id == ctx.outlet_id, DiningTable.active.is_(True)
    )
    if zone:
        query = query.where(DiningTable.zone == zone)
    zones: dict[str, list[tuple[str, str]]] = {}
    for table in await ctx.session.scalars(query.order_by(DiningTable.zone, DiningTable.label)):
        zones.setdefault(table.zone, []).append((table.label, qr_svg(table.qr_token)))
    if not zones:
        raise not_found("Tables")
    pdf = await render_pdf(qr_sheet_html(restaurant.brand_name, zones))
    return Response(pdf, media_type="application/pdf")


@router.get("/menu.pdf", responses=ERRORS)
async def menu_pdf(ctx: Ctx) -> Response:
    """Printable menu from current data: visible categories only."""
    assert_can(ctx.actor, Capability.VIEW_MENU, ctx.outlet_id)
    restaurant = await ctx.session.get(Restaurant, ctx.restaurant_id)
    outlet = await ctx.session.get(Outlet, ctx.outlet_id)
    assert restaurant is not None and outlet is not None
    menu = await load_menu(ctx)
    categories = [
        (c.name, [(i.name, i.description, i.base_price_paise, i.veg_flag) for i in c.items])
        for c in menu.categories
        if c.visible and c.items
    ]
    pdf = await render_pdf(menu_html(restaurant.brand_name, menu.prices_include_tax, categories))
    return Response(pdf, media_type="application/pdf")
