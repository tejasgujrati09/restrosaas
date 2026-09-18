from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tab(Base):
    __tablename__ = "tab"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"))
    table_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dining_table.id"))
    status: Mapped[str] = mapped_column(Text, default="open")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_by: Mapped[str] = mapped_column(Text)
    guest_count: Mapped[int | None] = mapped_column(Integer)
    customer_phone: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_charge_removed: Mapped[bool] = mapped_column(Boolean, default=False)


class TabSession(Base):
    __tablename__ = "tab_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    tab_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tab.id"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    device_fingerprint: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Order(Base):
    """A round on a tab. Named `tab_order` in SQL because `order` is reserved."""

    __tablename__ = "tab_order"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"))
    tab_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tab.id"))
    seq_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="placed")
    # Phase 3 hooks (CLAUDE.md §3): do not remove or hard-code around these.
    fulfillment_type: Mapped[str] = mapped_column(Text, default="dine_in")
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    placed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    placed_by_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tab_session.id"))
    source: Mapped[str] = mapped_column(Text)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderLine(Base):
    """Every price and name is a snapshot: menu edits never change a line."""

    __tablename__ = "order_line"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tab_order.id"))
    tab_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tab.id"))
    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_item.id"))
    item_name_snapshot: Mapped[str] = mapped_column(Text)
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_snapshot: Mapped[int] = mapped_column(Integer)
    price_rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    price_rule_name_snapshot: Mapped[str | None] = mapped_column(Text)
    tax_class_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    modifiers_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    line_total: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="placed")
    placed_by: Mapped[str] = mapped_column(Text)
    staff_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    needs_customer_ack: Mapped[bool] = mapped_column(Boolean, default=False)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(Text)


class TabEvent(Base):
    """Insert-only (the app role has no UPDATE or DELETE grant). The dispute log."""

    __tablename__ = "tab_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    tab_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tab.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_type: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    actor_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tab_session.id"))
    event: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reason: Mapped[str | None] = mapped_column(Text)


class ServiceRequest(Base):
    __tablename__ = "service_request"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"))
    tab_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tab.id"))
    type: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tab_session.id"))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
