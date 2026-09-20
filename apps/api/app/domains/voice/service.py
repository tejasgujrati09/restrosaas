"""Placing a phone order: the table-less tab and the round, through the same validation and
price snapshots as a guest's order. Prices, tax and totals come from the restaurant's menu,
computed in Python; the caller and the language model never supply them."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ordering import CartLine
from app.core.tab_totals import TabTotals, TotalsLine, compute_tab_totals
from app.domains.tab.events import Actor, emit
from app.domains.tab.models import Order, OrderLine, Tab
from app.domains.tab.service import OrderOrigin, build_snapshots, create_round
from app.domains.voice.models import Customer, CustomerAddress
from app.errors import ApiError

VOICE_FULFILLMENT = ("pickup", "delivery")
_MIN_PHONE_DIGITS = 8


def normalize_phone(raw: str | None) -> str | None:
    """A caller's number as one canonical string, or None when it is not a usable number
    (blocked or missing caller ID). Bare 10-digit numbers are Indian mobiles."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    if len(digits) < _MIN_PHONE_DIGITS or len(digits) > 15:
        return None
    return f"+{digits}"


@dataclass(frozen=True)
class VoicePlacement:
    order: Order
    lines: list[OrderLine]
    totals: TabTotals


async def find_customer(session: AsyncSession, restaurant_id: UUID, phone: str) -> Customer | None:
    customer: Customer | None = await session.scalar(
        select(Customer).where(Customer.restaurant_id == restaurant_id, Customer.phone == phone)
    )
    return customer


async def get_or_create_customer(
    session: AsyncSession, restaurant_id: UUID, phone: str, name: str | None, now: datetime
) -> Customer:
    customer = await find_customer(session, restaurant_id, phone)
    if customer is None:
        customer = Customer(
            restaurant_id=restaurant_id, phone=phone, name=_clean(name), created_at=now
        )
        session.add(customer)
        await session.flush()
    elif customer.name is None and _clean(name):
        customer.name = _clean(name)
    return customer


def _clean(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned[:120] or None


async def customer_addresses(session: AsyncSession, customer_id: UUID) -> list[CustomerAddress]:
    return list(
        await session.scalars(
            select(CustomerAddress)
            .where(CustomerAddress.customer_id == customer_id)
            .order_by(CustomerAddress.is_preferred.desc(), CustomerAddress.created_at)
        )
    )


async def add_address(
    session: AsyncSession,
    customer: Customer,
    address_text: str,
    *,
    make_preferred: bool,
    now: datetime,
) -> CustomerAddress:
    """Saves an address for a caller. Saying the same address again returns the saved one
    (compared ignoring case and spacing) instead of piling up duplicates."""
    text_clean = " ".join(address_text.split())
    if not text_clean:
        raise ApiError(422, "address_required", "The address is empty.")
    existing = await customer_addresses(session, customer.id)
    same = next(
        (a for a in existing if " ".join(a.address_text.split()).lower() == text_clean.lower()),
        None,
    )
    prefer = make_preferred or not existing
    if prefer:
        for a in existing:
            if a.is_preferred and a is not same:
                a.is_preferred = False
        await session.flush()
    if same is not None:
        if prefer:
            same.is_preferred = True
        return same
    address = CustomerAddress(
        restaurant_id=customer.restaurant_id,
        customer_id=customer.id,
        address_text=text_clean[:500],
        is_preferred=prefer,
        created_at=now,
    )
    session.add(address)
    await session.flush()
    return address


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
) -> VoicePlacement:
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
    placed = await create_round(
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
    totals = compute_tab_totals(
        [
            TotalsLine(
                unit_gross_paise=snap.unit_gross_paise,
                qty=snap.qty,
                rate_bp=snap.tax_class["rate_bp"],
                is_liquor=snap.tax_class["is_liquor"],
                prices_include_tax=snap.tax_class["prices_include_tax"],
            )
            for snap in snapshots
        ],
        service_charge_bp=outlet.service_charge_bp,
        service_charge_removed=tab.service_charge_removed,
    )
    return VoicePlacement(placed.order, placed.lines, totals)
