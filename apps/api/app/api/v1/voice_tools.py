"""The tools a restaurant's phone agent calls mid-call (docs/DECISIONS.md "Voice ordering
agent"). Machine endpoints, authenticated by the agent's `X-Voice-Key`, not by a person.

Every answer is `{"result": "<text>"}`: the platform hands that text to the language model, so
the wording is part of the contract. A business problem (unknown item, missing address) is an
ordinary 200 with a result that says what could not be done and what the agent must not
claim, because a non-200 would only reach the caller as a generic failure. The caller's phone
comes from a call variable bound in the tool config; the model never chooses who is calling.
Prices and totals come from the restaurant's menu, never from the model.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.auth import InvalidTokenError
from app.core.money import format_inr
from app.core.ordering import CartLine
from app.db.session import tenant_session
from app.domains.voice import service
from app.domains.voice.auth import matches, parse_voice_key
from app.domains.voice.models import Customer, CustomerAddress, VoiceAgent
from app.errors import ApiError
from app.idempotency import run_idempotent
from app.realtime.hooks import bind_outlet, run_after_commit

router = APIRouter(prefix="/v1/voice/tools", tags=["voice-tools"], include_in_schema=False)
logger = structlog.get_logger()

_NAMESPACE = uuid.UUID("5d0f7c9e-6a3b-4c1e-9b7a-2f4d8e1a6c30")
_DEDUPE_MINUTES = 5

_NO_PHONE = (
    "The caller's number is not available. Ask the caller for a mobile number and pass it as "
    "contact_phone. Do not guess a number."
)


@dataclass
class VoiceContext:
    session: AsyncSession
    restaurant_id: UUID
    outlet_id: UUID
    agent_id: UUID


def accepts_calls(agent: VoiceAgent, now: datetime) -> bool:
    """On, or turned off so recently that a call already in progress may still finish its
    order (`drain_until`, ten minutes after a disable). New calls are stopped at the platform."""
    if agent.status == "active":
        return True
    return agent.drain_until is not None and now < agent.drain_until


_REFUSED = ApiError(401, "invalid_voice_key", "This voice agent is not authorised.")


async def get_voice_context(
    x_voice_key: Annotated[str | None, Header(alias="X-Voice-Key")] = None,
) -> AsyncIterator[VoiceContext]:
    """One answer for every way the key can be wrong, so nothing leaks about which part
    failed. The key names the tenant; the hash proves possession; RLS confines the rest."""
    if not x_voice_key:
        raise _REFUSED
    try:
        restaurant_id, key_hash = parse_voice_key(x_voice_key)
    except InvalidTokenError as exc:
        raise _REFUSED from exc
    async with tenant_session(restaurant_id) as session:
        agent = await session.scalar(select(VoiceAgent).where(VoiceAgent.key_hash == key_hash))
        if (
            agent is None
            or not matches(agent.key_hash, key_hash)
            or not accepts_calls(agent, clock.utcnow())
        ):
            raise _REFUSED
        bind_outlet(session, agent.outlet_id)
        structlog.contextvars.bind_contextvars(
            restaurant_id=str(restaurant_id), outlet_id=str(agent.outlet_id), channel="voice"
        )
        yield VoiceContext(session, restaurant_id, agent.outlet_id, agent.id)
    await run_after_commit(session)


Voice = Annotated[VoiceContext, Depends(get_voice_context, scope="function")]


class ToolResult(BaseModel):
    result: str


class LookupIn(BaseModel):
    phone: str | None = None
    contact_phone: str | None = None


class SaveAddressIn(BaseModel):
    phone: str | None = None
    contact_phone: str | None = None
    name: str | None = Field(default=None, max_length=120)
    address: str = Field(max_length=500)
    make_preferred: bool = False


class OrderItemIn(BaseModel):
    item_id: str
    qty: int
    modifier_ids: list[str] = Field(default_factory=list, max_length=20)


class PlaceOrderIn(BaseModel):
    phone: str | None = None
    contact_phone: str | None = None
    name: str | None = Field(default=None, max_length=120)
    fulfillment: str
    items: list[OrderItemIn] = Field(max_length=50)
    address_id: str | None = None
    address: str | None = Field(default=None, max_length=500)
    call_id: str | None = Field(default=None, max_length=100)


def _caller(phone: str | None, contact_phone: str | None) -> str | None:
    return service.normalize_phone(phone) or service.normalize_phone(contact_phone)


def _describe_addresses(addresses: list[CustomerAddress]) -> str:
    return "; ".join(
        f'address_id={a.id} "{a.address_text}"' + (" (preferred)" if a.is_preferred else "")
        for a in addresses
    )


@router.post("/lookup_customer")
async def lookup_customer(body: LookupIn, ctx: Voice) -> ToolResult:
    phone = _caller(body.phone, body.contact_phone)
    if phone is None:
        return ToolResult(
            result="Caller number unavailable, so treat this as a new customer. "
            "Ask for their name, and for a mobile number and address if they want to order."
        )
    customer = await service.find_customer(ctx.session, ctx.restaurant_id, phone)
    if customer is None:
        return ToolResult(
            result="New customer: no saved name or address. Ask for their name, and for an "
            "address if they want delivery."
        )
    addresses = await service.customer_addresses(ctx.session, customer.id)
    name = customer.name or "name not saved"
    if not addresses:
        return ToolResult(
            result=f"Known customer ({name}) with no saved address. Ask for an address only "
            "if they want delivery."
        )
    return ToolResult(
        result=f"Known customer ({name}). Saved addresses: {_describe_addresses(addresses)}. "
        "For delivery, confirm which saved address to use, or take a new one."
    )


@router.post("/save_address")
async def save_address(body: SaveAddressIn, ctx: Voice) -> ToolResult:
    phone = _caller(body.phone, body.contact_phone)
    if phone is None:
        return ToolResult(result=f"Address not saved. {_NO_PHONE}")
    now = clock.utcnow()
    try:
        async with ctx.session.begin_nested():
            customer = await service.get_or_create_customer(
                ctx.session, ctx.restaurant_id, phone, body.name, now
            )
            address = await service.add_address(
                ctx.session, customer, body.address, make_preferred=body.make_preferred, now=now
            )
    except ApiError as exc:
        return ToolResult(result=f"Address not saved: {exc.message} Ask the caller again.")
    return ToolResult(result=f"Address saved. address_id={address.id}.")


def _refusal(message: str) -> ToolResult:
    return ToolResult(
        result=f"ORDER NOT PLACED: {message} Do not tell the caller an order was placed or "
        "sent. Fix the problem with the caller, or offer that the restaurant will call back."
    )


def _cart(items: list[OrderItemIn]) -> list[CartLine]:
    cart: list[CartLine] = []
    for item in items:
        try:
            cart.append(
                CartLine(UUID(item.item_id), item.qty, tuple(UUID(m) for m in item.modifier_ids))
            )
        except ValueError as exc:
            raise ApiError(
                422,
                "unknown_item",
                "An item id was not one of the ids in the menu list. Use only ids from the menu.",
            ) from exc
    return cart


def _dedupe_key(ctx: VoiceContext, body: PlaceOrderIn, phone: str, now_minute: int) -> UUID:
    """The same call retrying the same order gets the same key, so a repeated tool call places
    one order. Without a call id, calls within a few minutes stand in for 'the same call'."""
    cart = sorted(f"{i.item_id}:{i.qty}:{','.join(sorted(i.modifier_ids))}" for i in body.items)
    where = body.call_id or f"t{now_minute // _DEDUPE_MINUTES}"
    raw = "|".join(
        [
            str(ctx.agent_id),
            where,
            phone,
            body.fulfillment,
            *cart,
            body.address_id or (body.address or "").strip().lower(),
        ]
    )
    return uuid.uuid5(_NAMESPACE, raw)


@router.post("/place_order")
async def place_order(body: PlaceOrderIn, ctx: Voice) -> ToolResult:
    phone = _caller(body.phone, body.contact_phone)
    if phone is None:
        return _refusal(_NO_PHONE)
    now = clock.utcnow()
    try:
        async with ctx.session.begin_nested():
            return await _place(ctx, body, phone, now)
    except ApiError as exc:
        logger.info("voice_order_refused", code=exc.code)
        return _refusal(exc.message)


async def _place(ctx: VoiceContext, body: PlaceOrderIn, phone: str, now: datetime) -> ToolResult:
    cart = _cart(body.items)
    key = _dedupe_key(ctx, body, phone, int(now.timestamp() // 60))
    request_hash = hashlib.sha256(str(key).encode()).hexdigest()

    async def produce() -> ToolResult:
        customer = await service.get_or_create_customer(
            ctx.session, ctx.restaurant_id, phone, body.name, now
        )
        address = await _address_for(ctx.session, customer, body, now)
        placed = await service.place_voice_order(
            ctx.session,
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            customer=customer,
            address=address,
            fulfillment=body.fulfillment,
            cart=cart,
            call_id=body.call_id,
            now=now,
        )
        summary = ", ".join(f"{line.qty} x {line.item_name_snapshot}" for line in placed.lines)
        where = "for delivery" if body.fulfillment == "delivery" else "for pickup"
        return ToolResult(
            result=f"ORDER SENT FOR CONFIRMATION {where}, NOT YET CONFIRMED. Items: {summary}. "
            f"Estimated total {format_inr(placed.totals.estimated_total_paise)} including tax. "
            "Tell the caller the restaurant has received the order and will confirm it "
            "shortly. Do not say the order is confirmed or accepted."
        )

    return await run_idempotent(
        ctx.session, ctx.restaurant_id, ctx.agent_id, key, request_hash, ToolResult, produce
    )


async def _address_for(
    session: AsyncSession, customer: Customer, body: PlaceOrderIn, now: datetime
) -> CustomerAddress | None:
    if body.fulfillment != "delivery":
        return None
    if body.address_id:
        try:
            address_id = UUID(body.address_id)
        except ValueError as exc:
            raise ApiError(
                422, "address_required", "The address_id is not one from the saved list."
            ) from exc
        address = await session.get(CustomerAddress, address_id)
        if address is None or address.customer_id != customer.id:
            raise ApiError(
                422, "address_required", "That saved address does not belong to this caller."
            )
        return address
    if body.address and body.address.strip():
        return await service.add_address(
            session, customer, body.address, make_preferred=False, now=now
        )
    raise ApiError(422, "address_required", "A delivery order needs an address.")
