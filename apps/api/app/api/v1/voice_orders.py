"""Phone orders waiting for a person: list them, accept them, reject them. A phone order is
never accepted by a timer (docs/DECISIONS.md "Voice ordering agent")."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import clock
from app.api.v1.common import ERRORS, Ctx, IdempotencyKeyHeader, idempotent_write
from app.core.permissions import Capability, assert_can
from app.domains.tab import service
from app.domains.tab.models import Order, OrderLine, Tab
from app.domains.voice.models import Customer

router = APIRouter(prefix="/v1/outlets/{outlet_id}/staff/voice-orders", tags=["voice"])


class VoiceOrderLineOut(BaseModel):
    name: str
    qty: int
    line_total_paise: int


class VoiceOrderOut(BaseModel):
    order_id: UUID
    tab_id: UUID
    status: str
    fulfillment_type: str
    placed_at: datetime
    customer_name: str | None
    customer_phone: str | None
    delivery_address: str | None
    call_id: str | None
    total_paise: int
    lines: list[VoiceOrderLineOut]


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


async def _out(ctx: Ctx, order: Order, lines: list[OrderLine]) -> VoiceOrderOut:
    customer = await ctx.session.get(Customer, order.customer_id) if order.customer_id else None
    tab = await ctx.session.get(Tab, order.tab_id)
    return VoiceOrderOut(
        order_id=order.id,
        tab_id=order.tab_id,
        status=order.status,
        fulfillment_type=order.fulfillment_type,
        placed_at=order.placed_at,
        customer_name=customer.name if customer else None,
        customer_phone=customer.phone if customer else (tab.customer_phone if tab else None),
        delivery_address=order.delivery_address_snapshot,
        call_id=order.external_call_id,
        total_paise=sum(line.line_total for line in lines),
        lines=[
            VoiceOrderLineOut(name=x.item_name_snapshot, qty=x.qty, line_total_paise=x.line_total)
            for x in lines
        ],
    )


@router.get("", responses=ERRORS)
async def list_pending(ctx: Ctx) -> list[VoiceOrderOut]:
    """Phone orders still waiting to be accepted, oldest first."""
    assert_can(ctx.actor, Capability.ACCEPT_VOICE_ORDERS, ctx.outlet_id)
    orders = (
        await ctx.session.scalars(
            select(Order)
            .where(
                Order.outlet_id == ctx.outlet_id,
                Order.source == "voice",
                Order.status == "placed",
            )
            .order_by(Order.placed_at)
        )
    ).all()
    result: list[VoiceOrderOut] = []
    for order in orders:
        lines = list(
            await ctx.session.scalars(
                select(OrderLine)
                .where(OrderLine.order_id == order.id)
                .order_by(OrderLine.position, OrderLine.id)
            )
        )
        result.append(await _out(ctx, order, lines))
    return result


@router.post("/{order_id}/accept", responses=ERRORS)
async def accept(order_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> VoiceOrderOut:
    assert_can(ctx.actor, Capability.ACCEPT_VOICE_ORDERS, ctx.outlet_id)

    async def produce() -> VoiceOrderOut:
        order, lines = await service.accept_voice_order(ctx, order_id, clock.utcnow())
        return await _out(ctx, order, lines)

    return await idempotent_write(
        ctx, key, f"POST staff/voice-orders/{order_id}/accept", None, VoiceOrderOut, produce
    )


@router.post("/{order_id}/reject", responses=ERRORS)
async def reject(
    order_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: RejectIn
) -> VoiceOrderOut:
    assert_can(ctx.actor, Capability.ACCEPT_VOICE_ORDERS, ctx.outlet_id)

    async def produce() -> VoiceOrderOut:
        order, lines = await service.reject_voice_order(ctx, order_id, body.reason, clock.utcnow())
        return await _out(ctx, order, lines)

    return await idempotent_write(
        ctx, key, f"POST staff/voice-orders/{order_id}/reject", body, VoiceOrderOut, produce
    )
