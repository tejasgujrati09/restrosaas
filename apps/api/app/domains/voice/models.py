from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Customer(Base):
    """A caller, known by phone within one restaurant."""

    __tablename__ = "customer"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    phone: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerAddress(Base):
    __tablename__ = "customer_address"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    address_text: Mapped[str] = mapped_column(Text)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VoiceAgent(Base):
    """One phone ordering agent per outlet. `key_hash` is the hash of the secret the
    agent's tools send in `X-Voice-Key`; the secret itself is never stored here."""

    __tablename__ = "voice_agent"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlet.id"), unique=True)
    status: Mapped[str] = mapped_column(Text, default="enable_requested")
    gupshup_agent_id: Mapped[str | None] = mapped_column(Text)
    sr_plan_id: Mapped[int | None] = mapped_column(Integer)
    phone_number: Mapped[str | None] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    enabled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Provisioning steps that have succeeded, so a retry resumes instead of repeating them.
    completed_steps: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    failed_step: Mapped[str | None] = mapped_column(Text)
    # After a disable, a call already in progress may still place its order until this time.
    drain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))


class VoiceProvisioningAttempt(Base):
    """One run of the enable or disable job. `error` is internal detail for support; the
    owner only ever sees a plain message chosen from `failed_step`."""

    __tablename__ = "voice_provisioning_attempt"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant.id"))
    voice_agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voice_agent.id"))
    kind: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    requested_by_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(Text)
    failed_step: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
