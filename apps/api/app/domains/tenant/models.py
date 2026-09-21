from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core import flags
from app.db.base import Base


class Restaurant(Base):
    __tablename__ = "restaurant"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_name: Mapped[str] = mapped_column(Text)
    brand_name: Mapped[str] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(Text)
    subscription_plan: Mapped[str] = mapped_column(Text, default="trial")
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Outlet(Base):
    __tablename__ = "outlet"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    name: Mapped[str] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, default="Asia/Kolkata")
    state_code: Mapped[str] = mapped_column(Text)
    liquor_licensed: Mapped[bool] = mapped_column(Boolean, default=False)
    liquor_vat_rate_bp: Mapped[int] = mapped_column(Integer, default=0)
    service_charge_bp: Mapped[int] = mapped_column(Integer, default=0)
    prices_include_tax: Mapped[bool] = mapped_column(
        Boolean, default=flags.DEFAULT_PRICES_INCLUDE_TAX
    )
    ack_threshold_paise: Mapped[int] = mapped_column(
        Integer, default=flags.DEFAULT_ACK_THRESHOLD_PAISE
    )
    waiter_confirm_mode: Mapped[bool] = mapped_column(
        Boolean, default=flags.DEFAULT_WAITER_CONFIRM_MODE
    )
    liquor_approval_required: Mapped[bool] = mapped_column(
        Boolean, default=flags.DEFAULT_LIQUOR_APPROVAL_REQUIRED
    )
    expected_prep_minutes: Mapped[int] = mapped_column(
        Integer, default=flags.DEFAULT_EXPECTED_PREP_MINUTES
    )
    invoice_prefix: Mapped[str] = mapped_column(Text)
    next_invoice_no: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DiningTable(Base):
    """Physical table or bar seat (B1, B2, ...). Named `dining_table` because
    `table` is a reserved word in SQL."""

    __tablename__ = "dining_table"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"))
    label: Mapped[str] = mapped_column(Text)
    zone: Mapped[str] = mapped_column(Text, default="floor")
    seats: Mapped[int] = mapped_column(Integer, default=2)
    qr_token: Mapped[str] = mapped_column(Text, unique=True)
    requires_waiter_confirm: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Station(Base):
    __tablename__ = "station"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"))
    name: Mapped[str] = mapped_column(Text)
    printer_id: Mapped[str | None] = mapped_column(Text)


class TaxClass(Base):
    __tablename__ = "tax_class"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"))
    name: Mapped[str] = mapped_column(Text)
    gst_rate_bp: Mapped[int] = mapped_column(Integer, default=0)
    liquor_vat: Mapped[bool] = mapped_column(Boolean, default=False)
