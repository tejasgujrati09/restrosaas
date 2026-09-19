"""Placing a phone order: the table-less tab and the round, through the same validation and
price snapshots as a guest's order. Prices, tax and totals come from the restaurant's menu,
computed in Python; the caller and the language model never supply them."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ordering import CartLine
from app.domains.tab.events import Actor, emit
from app.domains.tab.models import Tab
from app.domains.tab.service import OrderOrigin, PlacedOrder, build_snapshots, create_round
from app.domains.voice.models import Customer, CustomerAddress
from app.errors import ApiError

VOICE_FULFILLMENT = ("pickup", "delivery")


async def place_voice_order(
    session: AsyncSession,
    *,
    restaurant_id: UUID,
    outlet_id: UUID,
    customer: Customer,
    address: CustomerAddress | None,
    fulfillment: str,
    cart: list[CartLine],
    call_id: str | None,
    now: datetime,
) -> PlacedOrder:
    """One order, one tab. The round stays `placed` until a manager or owner accepts it."""
    if fulfillment not in VOICE_FULFILLMENT:
        raise ApiError(422, "invalid_fulfillment", "Fulfilment must be pickup or delivery.")
    if not cart:
        raise ApiError(422, "empty_order", "The order has no items.")
    if fulfillment == "delivery" and address is None:
        raise ApiError(422, "address_required", "A delivery order needs an address.")

    outlet, loaded, snapshots = await build_snapshots(session, outlet_id, cart, now)

    tab = Tab(
        restaurant_id=restaurant_id,
        outlet_id=outlet_id,
        table_id=None,
        status="open",
        opened_at=now,
        opened_by="voice",
        customer_phone=customer.phone,
        confirmed_at=now,
    )
    session.add(tab)
    await session.flush()
    emit(
        session,
        restaurant_id=restaurant_id,
        tab_id=tab.id,
        table_id=None,
        at=now,
        actor=Actor("system"),
        event="opened",
        payload={"channel": "voice", "call_id": call_id},
    )

    origin = OrderOrigin(
        source="voice",
        fulfillment_type=fulfillment,
        customer_id=customer.id,
        address_id=address.id if fulfillment == "delivery" and address else None,
        delivery_address_snapshot=address.address_text
        if fulfillment == "delivery" and address
        else None,
        external_call_id=call_id,
    )
    return await create_round(
        session,
        restaurant_id=restaurant_id,
        outlet_id=outlet_id,
        tab=tab,
        snapshots=snapshots,
        notes={},
        loaded=loaded,
        actor=Actor("system"),
        now=now,
        outlet=outlet,
        origin=origin,
    )
