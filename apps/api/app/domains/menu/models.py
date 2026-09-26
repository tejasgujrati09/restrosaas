from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, Text, Time
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MenuCategory(Base):
    __tablename__ = "menu_category"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"))
    name: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    available_from: Mapped[time | None] = mapped_column(Time)
    available_to: Mapped[time | None] = mapped_column(Time)


class MenuItem(Base):
    __tablename__ = "menu_item"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"))
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_category.id"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # Exactly what the owner typed, in the outlet's `prices_include_tax` mode.
    base_price_paise: Mapped[int] = mapped_column(Integer)
    tax_class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tax_class.id"))
    station_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("station.id"))
    veg_flag: Mapped[bool] = mapped_column(Boolean, default=True)
    is_liquor: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    image_url: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    sku: Mapped[str | None] = mapped_column(Text)


class ModifierGroup(Base):
    __tablename__ = "modifier_group"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"))
    name: Mapped[str] = mapped_column(Text)
    min_select: Mapped[int] = mapped_column(Integer, default=0)
    max_select: Mapped[int] = mapped_column(Integer, default=1)


class Modifier(Base):
    __tablename__ = "modifier"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modifier_group.id"))
    name: Mapped[str] = mapped_column(Text)
    price_delta_paise: Mapped[int] = mapped_column(Integer, default=0)


class MenuItemModifierGroup(Base):
    __tablename__ = "menu_item_modifier_group"

    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_item.id"), primary_key=True)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modifier_group.id"), primary_key=True)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))


class PriceRule(Base):
    __tablename__ = "price_rule"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"))
    name: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    rule_type: Mapped[str] = mapped_column(Text)
    # fixed: paise. percent_off: percent * 100 (basis points, like tax rates).
    value: Mapped[int] = mapped_column(Integer)
    days_of_week: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MenuImport(Base):
    """One import-from-PDF-or-photos job (migration 0012). `files` holds storage keys only;
    `pages` the per-page progress and raw extraction; `rows` the owner's editable draft."""

    __tablename__ = "menu_import"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    status: Mapped[str] = mapped_column(Text, default="queued")
    stage: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    pages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    defaults: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
