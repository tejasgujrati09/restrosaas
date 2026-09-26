"""The waiter's floor: the table map, a table's tab, adding items for a guest, serving,
transferring and merging tabs, and the requests feed. Waiters see and act on their
assigned tables only; managers and owners on all (`app.domains.tab.access`)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app import clock
from app.api.v1.common import ERRORS, Ctx, IdempotencyKeyHeader, idempotent_write, not_found
from app.api.v1.guest import GuestMenuOut, build_guest_menu
from app.api.v1.tabs import (
    PlaceOrderIn,
    RoundOut,
    TabOut,
    _round_out,
    _staff_names,
    build_tab_out,
)
from app.core.floor import TableState, table_state
from app.core.ordering import CartLine
from app.core.permissions import Capability, Role, assert_can
from app.core.state import TabState, transition_tab
from app.core.tab_totals import TotalsLine, compute_tab_totals
from app.deps import OutletContext
from app.domains.staff.models import AppUser
from app.domains.tab import service, tickets
from app.domains.tab.access import require_table_access, sees_all_tables, visible_table_ids
from app.domains.tab.auto_assign import release_if_vacant
from app.domains.tab.events import Actor, emit
from app.domains.tab.models import (
    Order,
    OrderLine,
    ServiceRequest,
    Tab,
    TableAssignment,
    TabSession,
    Ticket,
)
from app.domains.tenant.models import DiningTable, Outlet
from app.errors import ApiError

router = APIRouter(prefix="/v1/outlets/{outlet_id}/staff", tags=["floor"])

_LIVE = service.LIVE_TAB_STATES
_GONE = ("cancelled", "voided")


class TableCardOut(BaseModel):
    id: UUID
    label: str
    zone: str
    seats: int
    active: bool
    state: TableState
    tab_id: UUID | None
    opened_at: datetime | None
    opened_by: str | None
    awaiting_confirm: bool
    estimated_total_paise: int
    # Rounds placed but not yet served or cancelled: the "new orders" badge.
    pending_rounds: int
    ready_rounds: int
    open_requests: list[str]
    awaiting_ack: int
    disputes: int
    waiters: list[str]


class TableMapOut(BaseModel):
    tables: list[TableCardOut]
    # True when the viewer is a waiter with no tables yet: show "ask your manager".
    unassigned: bool


@router.get("/table-map", responses=ERRORS)
async def table_map(ctx: Ctx) -> TableMapOut:
    """Every table the viewer may see, coloured by state, with the badges that say what
    needs doing. Waiters get their assigned tables only."""
    assert_can(ctx.actor, Capability.VIEW_TABLES_AND_TABS, ctx.outlet_id)
    session = ctx.session
    visible = await visible_table_ids(ctx)
    query = select(DiningTable).where(DiningTable.outlet_id == ctx.outlet_id)
    if visible is not None:
        query = query.where(DiningTable.id.in_(visible))
    tables = (await session.scalars(query.order_by(DiningTable.zone, DiningTable.label))).all()
    outlet = await session.get(Outlet, ctx.outlet_id)
    assert outlet is not None

    tab_by_table = {
        t.table_id: t
        for t in await session.scalars(
            select(Tab).where(
                Tab.outlet_id == ctx.outlet_id,
                Tab.status.in_(_LIVE),
                Tab.table_id.in_([t.id for t in tables]),
            )
        )
        if t.table_id
    }
    tab_ids = [t.id for t in tab_by_table.values()]
    orders_by_tab: dict[UUID, list[Order]] = {}
    lines_by_tab: dict[UUID, list[OrderLine]] = {}
    requests_by_tab: dict[UUID, list[str]] = {}
    if tab_ids:
        for order in await session.scalars(select(Order).where(Order.tab_id.in_(tab_ids))):
            orders_by_tab.setdefault(order.tab_id, []).append(order)
        for line in await session.scalars(select(OrderLine).where(OrderLine.tab_id.in_(tab_ids))):
            lines_by_tab.setdefault(line.tab_id, []).append(line)
        for tab_id, kind in await session.execute(
            select(ServiceRequest.tab_id, ServiceRequest.type).where(
                ServiceRequest.tab_id.in_(tab_ids), ServiceRequest.resolved_at.is_(None)
            )
        ):
            requests_by_tab.setdefault(tab_id, []).append(kind)
    waiter_names: dict[UUID, list[str]] = {}
    for table_id, name, phone in await session.execute(
        select(TableAssignment.table_id, AppUser.name, AppUser.phone)
        .join(AppUser, AppUser.id == TableAssignment.user_id)
        .where(TableAssignment.outlet_id == ctx.outlet_id)
        .order_by(AppUser.name)
    ):
        waiter_names.setdefault(table_id, []).append(name or phone)

    cards: list[TableCardOut] = []
    for table in tables:
        tab = tab_by_table.get(table.id)
        orders = orders_by_tab.get(tab.id, []) if tab else []
        lines = lines_by_tab.get(tab.id, []) if tab else []
        live_lines = [
            line
            for line in lines
            if line.status not in _GONE
            and next((o for o in orders if o.id == line.order_id), None) is not None
        ]
        active_orders = {o.id for o in orders if o.status != "cancelled"}
        totals = compute_tab_totals(
            [
                TotalsLine(
                    unit_gross_paise=line.line_total // line.qty,
                    qty=line.qty,
                    rate_bp=line.tax_class_snapshot["rate_bp"],
                    is_liquor=line.tax_class_snapshot["is_liquor"],
                    prices_include_tax=line.tax_class_snapshot["prices_include_tax"],
                )
                for line in live_lines
                if line.order_id in active_orders
            ],
            service_charge_bp=outlet.service_charge_bp,
            service_charge_removed=bool(tab and tab.service_charge_removed),
        )
        statuses = [o.status for o in orders]
        cards.append(
            TableCardOut(
                id=table.id,
                label=table.label,
                zone=table.zone,
                seats=table.seats,
                active=table.active,
                state=table_state(tab.status if tab else None, statuses),
                tab_id=tab.id if tab else None,
                opened_at=tab.opened_at if tab else None,
                opened_by=tab.opened_by if tab else None,
                awaiting_confirm=bool(tab and tab.confirmed_at is None),
                estimated_total_paise=totals.estimated_total_paise,
                pending_rounds=sum(1 for s in statuses if s in ("placed", "accepted", "preparing")),
                ready_rounds=sum(1 for s in statuses if s == "ready"),
                open_requests=sorted(requests_by_tab.get(tab.id, [])) if tab else [],
                awaiting_ack=sum(
                    1
                    for line in live_lines
                    if line.needs_customer_ack and not line.acked_at and not line.disputed_at
                ),
                disputes=sum(1 for line in live_lines if line.disputed_at),
                waiters=waiter_names.get(table.id, []),
            )
        )
    unassigned = not sees_all_tables(ctx) and not tables
    return TableMapOut(tables=cards, unassigned=unassigned)


class StaffTabOut(BaseModel):
    tab: TabOut
    table_id: UUID | None
    opened_by: str
    # Phones currently able to act on this tab; none means a walk-in nobody can ack for.
    guest_sessions: int


async def _staff_tab(
    ctx: OutletContext, tab_id: UUID, *, lock: bool = False, live: bool = True
) -> Tab:
    query = select(Tab).where(Tab.id == tab_id, Tab.outlet_id == ctx.outlet_id)
    tab = await ctx.session.scalar(query.with_for_update() if lock else query)
    if tab is None:
        raise not_found("Tab")
    await require_table_access(ctx, tab.table_id)
    if live and tab.status not in _LIVE:
        raise ApiError(409, "tab_not_open", "This tab is already closed.", {"status": tab.status})
    return tab


async def _staff_tab_out(ctx: OutletContext, tab: Tab) -> StaffTabOut:
    now = clock.utcnow()
    await service.accept_due_orders(ctx.session, ctx.restaurant_id, tab.id, now)
    sessions = await ctx.session.scalar(
        select(func.count())
        .select_from(TabSession)
        .where(
            TabSession.tab_id == tab.id,
            TabSession.revoked.is_(False),
            TabSession.expires_at > now,
        )
    )
    view = await build_tab_out(ctx.session, ctx.outlet_id, tab, None)
    return StaffTabOut(
        tab=view, table_id=tab.table_id, opened_by=tab.opened_by, guest_sessions=sessions or 0
    )


@router.get("/tabs/{tab_id}", responses=ERRORS)
async def get_staff_tab(tab_id: UUID, ctx: Ctx) -> StaffTabOut:
    assert_can(ctx.actor, Capability.VIEW_TABLES_AND_TABS, ctx.outlet_id)
    return await _staff_tab_out(ctx, await _staff_tab(ctx, tab_id, live=False))


@router.get("/menu", responses=ERRORS)
async def staff_menu(ctx: Ctx) -> GuestMenuOut:
    """The menu as the guest sees it, prices as of now, for adding items to a table."""
    assert_can(ctx.actor, Capability.ADD_ORDER_LINES, ctx.outlet_id)
    return await build_guest_menu(ctx.session, ctx.outlet_id, clock.utcnow())


class OpenTabIn(BaseModel):
    guest_count: int | None = Field(default=None, ge=1, le=100)


class OpenTabOut(BaseModel):
    tab_id: UUID
    # False when the table already had a tab, which is returned instead.
    created: bool


@router.post("/tables/{table_id}/tab", responses=ERRORS)
async def open_walk_in_tab(
    table_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: OpenTabIn
) -> OpenTabOut:
    """Opens a tab for a walk-in without a phone or a QR scan. With nobody on it to
    tap "Yes, ours", lines the waiter adds above the threshold are waived and logged."""
    assert_can(ctx.actor, Capability.OPEN_TRANSFER_MERGE_TABS, ctx.outlet_id)

    async def produce() -> OpenTabOut:
        table = await ctx.session.get(DiningTable, table_id)
        if table is None or table.outlet_id != ctx.outlet_id or not table.active:
            raise not_found("Table")
        await require_table_access(ctx, table_id, "Table")
        now = clock.utcnow()
        created = await ctx.session.scalar(
            insert(Tab)
            .values(
                id=uuid4(),
                restaurant_id=ctx.restaurant_id,
                outlet_id=ctx.outlet_id,
                table_id=table_id,
                status="open",
                opened_at=now,
                opened_by="waiter",
                guest_count=body.guest_count,
                confirmed_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[Tab.table_id], index_where=service.LIVE_TAB_INDEX_PREDICATE
            )
            .returning(Tab.id)
        )
        if created is not None:
            emit(
                ctx.session,
                restaurant_id=ctx.restaurant_id,
                tab_id=created,
                table_id=table_id,
                at=now,
                actor=Actor("staff", user_id=ctx.actor.user_id),
                event="opened",
                payload={"table": table.label, "walk_in": True},
            )
            return OpenTabOut(tab_id=created, created=True)
        existing = await ctx.session.scalar(
            select(Tab.id).where(Tab.table_id == table_id, Tab.status.in_(_LIVE))
        )
        if existing is None:
            raise ApiError(409, "try_again", "Please try again.")
        return OpenTabOut(tab_id=existing, created=False)

    return await idempotent_write(
        ctx, key, f"POST staff/tables/{table_id}/tab", body, OpenTabOut, produce
    )


@router.post("/tabs/{tab_id}/orders", status_code=201, responses=ERRORS)
async def add_items_for_guest(
    tab_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: PlaceOrderIn
) -> RoundOut:
    """A waiter adds a round. It is accepted at once (no undo window), each line records
    the waiter, and lines at or above the outlet's threshold ask the guest to confirm."""
    assert_can(ctx.actor, Capability.ADD_ORDER_LINES, ctx.outlet_id)

    async def produce() -> RoundOut:
        now = clock.utcnow()
        tab = await _staff_tab(ctx, tab_id, lock=True)
        if tab.confirmed_at is None:
            # A waiter attending the table is the confirmation waiter-confirm mode asks for.
            tab.confirmed_at = now
            emit(
                ctx.session,
                restaurant_id=ctx.restaurant_id,
                tab_id=tab.id,
                table_id=tab.table_id,
                at=now,
                actor=Actor("staff", user_id=ctx.actor.user_id),
                event="confirmed",
            )
        cart = [CartLine(c.menu_item_id, c.qty, tuple(c.modifier_ids)) for c in body.lines]
        notes = {i: c.note for i, c in enumerate(body.lines)}
        approver = any(
            outlet == ctx.outlet_id and role in (Role.MANAGER, Role.OWNER)
            for outlet, role in ctx.actor.roles
        )
        placed = await service.place_staff_order(
            ctx, tab, cart, notes, now, approval_granted=approver
        )
        names = await _staff_names(ctx.session, placed.lines)
        return _round_out(placed.order, placed.lines, None, names)

    return await idempotent_write(
        ctx, key, f"POST staff/tabs/{tab_id}/orders", body, RoundOut, produce
    )


class ServeIn(BaseModel):
    # Omit to serve everything in the round that is ready.
    line_ids: list[UUID] | None = Field(default=None, max_length=100)


@router.post("/tabs/{tab_id}/orders/{order_id}/serve", responses=ERRORS)
async def mark_served(
    tab_id: UUID, order_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: ServeIn
) -> RoundOut:
    assert_can(ctx.actor, Capability.MARK_ORDER_SERVED, ctx.outlet_id)

    async def produce() -> RoundOut:
        tab = await _staff_tab(ctx, tab_id, lock=True)
        order = await tickets.serve_lines(
            ctx.session,
            restaurant_id=ctx.restaurant_id,
            tab=tab,
            order_id=order_id,
            line_ids=body.line_ids,
            user_id=ctx.actor.user_id,
            now=clock.utcnow(),
        )
        lines = list(
            await ctx.session.scalars(
                select(OrderLine)
                .where(OrderLine.order_id == order.id)
                .order_by(OrderLine.position, OrderLine.id)
            )
        )
        return _round_out(order, lines, None, await _staff_names(ctx.session, lines))

    return await idempotent_write(
        ctx, key, f"POST staff/tabs/{tab_id}/orders/{order_id}/serve", body, RoundOut, produce
    )


class TransferIn(BaseModel):
    table_id: UUID


@router.post("/tabs/{tab_id}/transfer", responses=ERRORS)
async def transfer_tab(
    tab_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: TransferIn
) -> StaffTabOut:
    """Moves a tab to a free table. If someone is already seated there the answer is
    409 `table_occupied` naming that tab, so the app can offer to merge instead."""
    assert_can(ctx.actor, Capability.OPEN_TRANSFER_MERGE_TABS, ctx.outlet_id)

    async def produce() -> StaffTabOut:
        tab = await _staff_tab(ctx, tab_id, lock=True)
        target = await ctx.session.get(DiningTable, body.table_id)
        if target is None or target.outlet_id != ctx.outlet_id or not target.active:
            raise not_found("Table")
        await require_table_access(ctx, target.id, "Table")
        if tab.table_id == target.id:
            raise ApiError(409, "same_table", "The tab is already at that table.")
        occupant = await ctx.session.scalar(
            select(Tab.id).where(Tab.table_id == target.id, Tab.status.in_(_LIVE))
        )
        if occupant is not None:
            raise ApiError(
                409,
                "table_occupied",
                "Someone is already at that table. Merge the tabs instead?",
                {"tab_id": str(occupant)},
            )
        source = await ctx.session.get(DiningTable, tab.table_id) if tab.table_id else None
        from_id = tab.table_id
        tab.table_id = target.id
        try:
            await ctx.session.flush()
        except IntegrityError as exc:  # someone sat down there a moment ago
            raise ApiError(409, "table_occupied", "Someone just sat at that table.") from exc
        await release_if_vacant(ctx.session, from_id)
        emit(
            ctx.session,
            restaurant_id=ctx.restaurant_id,
            tab_id=tab.id,
            table_id=target.id,
            at=clock.utcnow(),
            actor=Actor("staff", user_id=ctx.actor.user_id),
            event="transferred",
            payload={
                "from_table_id": str(from_id) if from_id else None,
                "to_table_id": str(target.id),
                "from": source.label if source else None,
                "to": target.label,
            },
        )
        return await _staff_tab_out(ctx, tab)

    return await idempotent_write(
        ctx, key, f"POST staff/tabs/{tab_id}/transfer", body, StaffTabOut, produce
    )


class MergeIn(BaseModel):
    into_tab_id: UUID


@router.post("/tabs/{tab_id}/merge", responses=ERRORS)
async def merge_tab(
    tab_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: MergeIn
) -> StaffTabOut:
    """Folds this tab into another: every round, line, request and guest phone moves to
    the surviving tab, and this one is voided, empty. Nothing is edited or deleted, and
    both tabs' event logs record it."""
    assert_can(ctx.actor, Capability.OPEN_TRANSFER_MERGE_TABS, ctx.outlet_id)

    async def produce() -> StaffTabOut:
        if body.into_tab_id == tab_id:
            raise ApiError(409, "same_tab", "A tab can't be merged into itself.")
        # Lock both in a fixed order so two waiters merging opposite ways can't deadlock.
        locked = {
            t.id: t
            for t in await ctx.session.scalars(
                select(Tab)
                .where(Tab.id.in_([tab_id, body.into_tab_id]), Tab.outlet_id == ctx.outlet_id)
                .order_by(Tab.id)
                .with_for_update()
            )
        }
        source, target = locked.get(tab_id), locked.get(body.into_tab_id)
        if source is None or target is None:
            raise not_found("Tab")
        for tab in (source, target):
            await require_table_access(ctx, tab.table_id)
            if tab.status not in _LIVE:
                raise ApiError(409, "tab_not_open", "A closed tab can't be merged.")
        now = clock.utcnow()
        actor = Actor("staff", user_id=ctx.actor.user_id)
        session = ctx.session

        moved = list(
            await session.scalars(
                select(Order)
                .where(Order.tab_id == source.id)
                .order_by(Order.placed_at, Order.seq_no)
            )
        )
        base = (
            await session.scalar(select(func.max(Order.seq_no)).where(Order.tab_id == target.id))
        ) or 0
        # Renumber into the survivor's sequence, in the order they were placed. Two passes
        # keep the (tab, seq) unique constraint happy while rows are in flight.
        for index, order in enumerate(moved, start=1):
            order.seq_no = base + index
            order.tab_id = target.id
        await session.flush()
        for model in (OrderLine, Ticket):
            await session.execute(
                update(model).where(model.tab_id == source.id).values(tab_id=target.id)
            )
        sessions_moved = len(
            (
                await session.execute(
                    update(TabSession)
                    .where(TabSession.tab_id == source.id)
                    .values(tab_id=target.id)
                    .returning(TabSession.id)
                )
            ).all()
        )
        # An open request of a type the survivor already has would collide: close it.
        open_types = set(
            await session.scalars(
                select(ServiceRequest.type).where(
                    ServiceRequest.tab_id == target.id, ServiceRequest.resolved_at.is_(None)
                )
            )
        )
        for request in await session.scalars(
            select(ServiceRequest).where(
                ServiceRequest.tab_id == source.id, ServiceRequest.resolved_at.is_(None)
            )
        ):
            if request.type in open_types:
                request.resolved_at, request.resolved_by = now, ctx.actor.user_id
            open_types.add(request.type)
            request.tab_id = target.id
        await session.flush()

        from_table = await session.get(DiningTable, source.table_id) if source.table_id else None
        to_table = await session.get(DiningTable, target.table_id) if target.table_id else None
        summary = {
            "from_tab_id": str(source.id),
            "into_tab_id": str(target.id),
            "from_table_id": str(source.table_id) if source.table_id else None,
            "from": from_table.label if from_table else None,
            "into": to_table.label if to_table else None,
            "rounds": len(moved),
            "guest_phones": sessions_moved,
        }
        emit(
            session,
            restaurant_id=ctx.restaurant_id,
            tab_id=source.id,
            table_id=source.table_id,
            at=now,
            actor=actor,
            event="merged",
            payload=summary,
        )
        if TabState(source.status) == TabState.BILL_REQUESTED:
            source.status = transition_tab(TabState.BILL_REQUESTED, TabState.OPEN).value
        source.status = transition_tab(TabState(source.status), TabState.VOIDED).value
        source.closed_at = now
        await session.flush()
        await release_if_vacant(session, source.table_id)
        emit(
            session,
            restaurant_id=ctx.restaurant_id,
            tab_id=target.id,
            table_id=target.table_id,
            at=now,
            actor=actor,
            event="merged",
            payload=summary,
        )
        return await _staff_tab_out(ctx, target)

    return await idempotent_write(
        ctx, key, f"POST staff/tabs/{tab_id}/merge", body, StaffTabOut, produce
    )


class RequestRowOut(BaseModel):
    id: UUID
    type: str
    tab_id: UUID
    table_id: UUID | None
    table_label: str | None
    created_at: datetime


@router.get("/service-requests", responses=ERRORS)
async def list_requests(ctx: Ctx) -> list[RequestRowOut]:
    """Open water / waiter / bill requests, oldest first, for the tables the viewer may see."""
    assert_can(ctx.actor, Capability.VIEW_TABLES_AND_TABS, ctx.outlet_id)
    visible = await visible_table_ids(ctx)
    query = (
        select(ServiceRequest, Tab.table_id, DiningTable.label)
        .join(Tab, Tab.id == ServiceRequest.tab_id)
        .outerjoin(DiningTable, DiningTable.id == Tab.table_id)
        .where(ServiceRequest.outlet_id == ctx.outlet_id, ServiceRequest.resolved_at.is_(None))
        .order_by(ServiceRequest.created_at)
    )
    if visible is not None:
        query = query.where(Tab.table_id.in_(visible))
    return [
        RequestRowOut(
            id=r.id,
            type=r.type,
            tab_id=r.tab_id,
            table_id=table_id,
            table_label=label,
            created_at=r.created_at,
        )
        for r, table_id, label in (await ctx.session.execute(query)).tuples()
    ]


@router.post("/service-requests/{request_id}/resolve", responses=ERRORS)
async def resolve_request(request_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> RequestRowOut:
    assert_can(ctx.actor, Capability.VIEW_TABLES_AND_TABS, ctx.outlet_id)

    async def produce() -> RequestRowOut:
        request = await ctx.session.scalar(
            select(ServiceRequest)
            .where(ServiceRequest.id == request_id, ServiceRequest.outlet_id == ctx.outlet_id)
            .with_for_update()
        )
        if request is None:
            raise not_found("Request")
        tab = await ctx.session.get(Tab, request.tab_id)
        assert tab is not None
        await require_table_access(ctx, tab.table_id, "Request")
        table = await ctx.session.get(DiningTable, tab.table_id) if tab.table_id else None
        if request.resolved_at is None:
            now = clock.utcnow()
            request.resolved_at, request.resolved_by = now, ctx.actor.user_id
            emit(
                ctx.session,
                restaurant_id=ctx.restaurant_id,
                tab_id=tab.id,
                table_id=tab.table_id,
                at=now,
                actor=Actor("staff", user_id=ctx.actor.user_id),
                event="service_request_resolved",
                payload={"request_id": str(request.id), "type": request.type},
            )
        return RequestRowOut(
            id=request.id,
            type=request.type,
            tab_id=tab.id,
            table_id=tab.table_id,
            table_label=table.label if table else None,
            created_at=request.created_at,
        )

    return await idempotent_write(
        ctx, key, f"POST staff/service-requests/{request_id}/resolve", None, RequestRowOut, produce
    )


class AlertOut(BaseModel):
    kind: Literal["line_disputed", "ack_pending"]
    tab_id: UUID
    table_label: str | None
    line_id: UUID
    item: str
    line_total_paise: int
    staff_name: str | None
    since: datetime


@router.get("/alerts", responses=ERRORS)
async def alerts(ctx: Ctx) -> list[AlertOut]:
    """For managers: items a guest says are not theirs, and staff-added items still waiting
    for the guest's OK after three minutes. Voiding is a manager action (Milestone 5)."""
    assert_can(ctx.actor, Capability.VOID_OR_DISCOUNT_LINE, ctx.outlet_id)
    now = clock.utcnow()
    rows = await ctx.session.execute(
        select(OrderLine, Order.placed_at, DiningTable.label, AppUser.name)
        .join(Order, Order.id == OrderLine.order_id)
        .join(Tab, Tab.id == OrderLine.tab_id)
        .outerjoin(DiningTable, DiningTable.id == Tab.table_id)
        .outerjoin(AppUser, AppUser.id == OrderLine.staff_user_id)
        .where(
            Tab.outlet_id == ctx.outlet_id,
            Tab.status.in_(_LIVE),
            OrderLine.needs_customer_ack.is_(True),
            OrderLine.status.not_in(_GONE),
            OrderLine.acked_at.is_(None),
        )
        .order_by(Order.placed_at)
    )
    out: list[AlertOut] = []
    kind: Literal["line_disputed", "ack_pending"]
    for line, placed_at, label, staff_name in rows.tuples():
        if line.disputed_at is not None:
            kind, since = "line_disputed", line.disputed_at
        elif (now - placed_at).total_seconds() > 180:
            kind, since = "ack_pending", placed_at
        else:
            continue
        out.append(
            AlertOut(
                kind=kind,
                tab_id=line.tab_id,
                table_label=label,
                line_id=line.id,
                item=line.item_name_snapshot,
                line_total_paise=line.line_total,
                staff_name=staff_name,
                since=since,
            )
        )
    return out
