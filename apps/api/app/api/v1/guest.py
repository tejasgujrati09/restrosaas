"""What a guest sees before and while ordering: the QR landing, which turns a
table's QR token into a TabSession, and the menu with prices as of now."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.api.v1.common import ERRORS, GuestCtx
from app.auth import InvalidTokenError
from app.core.ordering import category_is_open
from app.core.pricing import PricedItem, effective_price, next_boundary
from app.db.session import qr_session, tenant_session
from app.domains.menu.orderable import load_items, load_price_rules
from app.domains.tab.events import record_event
from app.domains.tab.models import Tab, TabSession
from app.domains.tab.service import LIVE_TAB_INDEX_PREDICATE, LIVE_TAB_STATES
from app.domains.tenant.models import DiningTable, Outlet, Restaurant
from app.errors import ApiError
from app.guest_auth import SESSION_TTL_HOURS, new_session_token, parse_session_token
from app.realtime.hooks import bind_outlet, run_after_commit

router = APIRouter(tags=["guest"])
_optional_bearer = HTTPBearer(auto_error=False)

_QR_INVALID = ApiError(
    404, "qr_not_found", "This QR code is no longer valid. Please ask your waiter."
)


class QrSessionIn(BaseModel):
    device_fingerprint: str | None = Field(default=None, max_length=200)


class QrSessionOut(BaseModel):
    # Null when the phone's existing session for this tab is still good: keep using it.
    session_token: str | None
    expires_at: datetime
    outlet_id: UUID
    outlet_name: str
    table_label: str
    tab_id: UUID
    tab_status: str
    awaiting_waiter: bool


@router.post("/v1/qr/{qr_token}/session", responses=ERRORS)
async def open_session(
    qr_token: str,
    body: QrSessionIn,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
) -> QrSessionOut:
    """Exchanges a table's QR token for a TabSession, joining the table's live
    tab or opening one. Anonymous: the QR token is the credential. Scanning again
    with a still-valid session for the same tab returns that session's expiry
    instead of minting another."""
    if len(qr_token) > 64:
        raise _QR_INVALID
    async with qr_session(qr_token) as lookup:
        found = (
            await lookup.execute(
                select(DiningTable.restaurant_id, DiningTable.id).where(
                    DiningTable.qr_token == qr_token
                )
            )
        ).first()
    if found is None:
        raise _QR_INVALID
    restaurant_id, table_id = found._tuple()

    now = clock.utcnow()
    async with tenant_session(restaurant_id) as session:
        table = await session.get(DiningTable, table_id)
        if table is None or table.qr_token != qr_token or not table.active:
            raise _QR_INVALID
        restaurant = await session.get(Restaurant, restaurant_id)
        outlet = await session.get(Outlet, table.outlet_id)
        assert restaurant is not None and outlet is not None
        bind_outlet(session, outlet.id)
        if restaurant.status != "active":
            raise ApiError(403, "outlet_unavailable", "This venue is not taking orders right now.")

        needs_confirm = outlet.waiter_confirm_mode or table.requires_waiter_confirm
        tab: Tab | None = None
        is_new_tab = False
        for _ in range(3):
            opened = await session.scalar(
                insert(Tab)
                .values(
                    id=uuid4(),
                    restaurant_id=restaurant_id,
                    outlet_id=outlet.id,
                    table_id=table.id,
                    status="open",
                    opened_at=now,
                    opened_by="customer",
                    confirmed_at=None if needs_confirm else now,
                )
                .on_conflict_do_nothing(
                    index_elements=[Tab.table_id], index_where=LIVE_TAB_INDEX_PREDICATE
                )
                .returning(Tab.id)
            )
            if opened is not None:
                tab = await session.get(Tab, opened)
                assert tab is not None
                is_new_tab = True
            else:
                tab = await session.scalar(
                    select(Tab).where(Tab.table_id == table.id, Tab.status.in_(LIVE_TAB_STATES))
                )
                is_new_tab = False
            if tab is not None:
                break
        if tab is None:
            raise ApiError(409, "try_again", "Please scan the QR code again.")

        current: TabSession | None = None
        if credentials is not None:
            try:
                token_restaurant, token_hash = parse_session_token(credentials.credentials)
            except InvalidTokenError:
                token_restaurant, token_hash = None, ""
            if token_restaurant == restaurant_id:
                current = await session.scalar(
                    select(TabSession).where(
                        TabSession.token_hash == token_hash,
                        TabSession.tab_id == tab.id,
                        TabSession.revoked.is_(False),
                        TabSession.expires_at > now,
                    )
                )

        if current is not None:
            new_token: str | None = None
            tab_session = current
        else:
            new_token, token_hash = new_session_token(restaurant_id)
            tab_session = TabSession(
                id=uuid4(),
                restaurant_id=restaurant_id,
                tab_id=tab.id,
                token_hash=token_hash,
                device_fingerprint=body.device_fingerprint,
                created_at=now,
                expires_at=now + timedelta(hours=SESSION_TTL_HOURS),
            )
            session.add(tab_session)
            await session.flush()
        if is_new_tab:
            record_event(
                session,
                restaurant_id=restaurant_id,
                tab_id=tab.id,
                at=now,
                actor_type="customer",
                actor_session_id=tab_session.id,
                event="opened",
                table_id=table.id,
                payload={"table": table.label},
            )
        result = QrSessionOut(
            session_token=new_token,
            expires_at=tab_session.expires_at,
            outlet_id=outlet.id,
            outlet_name=outlet.name,
            table_label=table.label,
            tab_id=tab.id,
            tab_status=tab.status,
            awaiting_waiter=tab.confirmed_at is None,
        )
    await run_after_commit(session)
    return result


class RuleBadgeOut(BaseModel):
    id: UUID
    name: str
    # When today's window ends, e.g. "happy hour until 8 PM". Null for all-day rules.
    ends_at: datetime | None


class GuestModifierOut(BaseModel):
    id: UUID
    name: str
    price_delta_paise: int


class GuestModifierGroupOut(BaseModel):
    id: UUID
    name: str
    min_select: int
    max_select: int
    modifiers: list[GuestModifierOut]


class GuestItemOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    veg: bool
    is_liquor: bool
    image_url: str | None
    price_paise: int
    base_price_paise: int
    price_rule: RuleBadgeOut | None
    available: bool
    # False for items the guest may not add themselves (liquor needing approval).
    self_orderable: bool
    modifier_groups: list[GuestModifierGroupOut]


class GuestCategoryOut(BaseModel):
    id: UUID
    name: str
    items: list[GuestItemOut]


class GuestMenuOut(BaseModel):
    outlet_name: str
    prices_include_tax: bool
    service_charge_bp: int
    categories: list[GuestCategoryOut]


async def build_guest_menu(session: AsyncSession, outlet_id: UUID, now: datetime) -> GuestMenuOut:
    """Visible categories that are open now, with each item's price as of now and
    the happy-hour badge when a rule applies. Sold-out items are listed, marked.
    Used for guests and for a waiter adding items, so both see the same menu."""
    outlet = await session.get(Outlet, outlet_id)
    assert outlet is not None
    tz = ZoneInfo(outlet.timezone)
    local_now = now.astimezone(tz).time()
    rules, names = await load_price_rules(session, outlet_id)
    rules_by_id = {r.id: r for r in rules}
    loaded = await load_items(session, outlet_id, outlet.liquor_vat_rate_bp)

    categories: dict[UUID, GuestCategoryOut] = {}
    for entry in loaded.values():
        o = entry.orderable
        if not (o.category_visible and category_is_open(o.category_from, o.category_to, local_now)):
            continue
        row = entry.row
        price = effective_price(
            PricedItem(row.id, row.category_id, row.base_price_paise), rules, now, tz
        )
        badge = None
        if price.price_rule_id is not None:
            badge = RuleBadgeOut(
                id=price.price_rule_id,
                name=names[price.price_rule_id],
                ends_at=next_boundary(rules_by_id[price.price_rule_id], now, tz),
            )
        item_out = GuestItemOut(
            id=row.id,
            name=row.name,
            description=row.description,
            veg=row.veg_flag,
            is_liquor=row.is_liquor,
            image_url=row.image_url,
            price_paise=price.unit_price_paise,
            base_price_paise=row.base_price_paise,
            price_rule=badge,
            available=row.available and (not row.is_liquor or outlet.liquor_licensed),
            self_orderable=not (row.needs_approval and outlet.liquor_approval_required),
            modifier_groups=[
                GuestModifierGroupOut(
                    id=g.id,
                    name=g.name,
                    min_select=g.min_select,
                    max_select=g.max_select,
                    modifiers=[
                        GuestModifierOut(
                            id=m.id, name=m.name, price_delta_paise=m.price_delta_paise
                        )
                        for m in g.modifiers
                    ],
                )
                for g in o.groups
            ],
        )
        category = categories.setdefault(
            entry.category.id,
            GuestCategoryOut(id=entry.category.id, name=entry.category.name, items=[]),
        )
        category.items.append(item_out)

    sort_keys = {e.category.id: (e.category.sort_order, e.category.name) for e in loaded.values()}
    ordered = sorted(categories.values(), key=lambda c: sort_keys[c.id])
    return GuestMenuOut(
        outlet_name=outlet.name,
        prices_include_tax=outlet.prices_include_tax,
        service_charge_bp=outlet.service_charge_bp,
        categories=ordered,
    )


@router.get("/v1/outlets/{outlet_id}/guest/menu", responses=ERRORS)
async def guest_menu(ctx: GuestCtx) -> GuestMenuOut:
    return await build_guest_menu(ctx.session, ctx.outlet_id, clock.utcnow())


class GuestSessionOut(BaseModel):
    tab_id: UUID
    table_label: str | None
    tab_status: str
    awaiting_waiter: bool


@router.get("/v1/outlets/{outlet_id}/guest/session", responses=ERRORS)
async def guest_session(ctx: GuestCtx) -> GuestSessionOut:
    """Which tab this phone is on now. It changes when a waiter merges the table's tab
    into another, so the app asks again after a merge instead of trusting what it stored."""
    tab = await ctx.session.get(Tab, ctx.tab_id)
    assert tab is not None
    table = await ctx.session.get(DiningTable, tab.table_id) if tab.table_id else None
    return GuestSessionOut(
        tab_id=tab.id,
        table_label=table.label if table else None,
        tab_status=tab.status,
        awaiting_waiter=tab.confirmed_at is None,
    )
