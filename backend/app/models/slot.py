"""Slot model (§4, §2.7) — a pre-generated labeling opportunity carrying its
variant assignment. Slots are leased by the assignment engine (M2)."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin

SLOT_STATUSES = ("open", "leased", "filled", "voided")


class Slot(TimestampMixin, Base):
    __tablename__ = "slots"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'leased', 'filled', 'voided')", name="ck_slots_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(
        ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    leased_by: Mapped[int | None] = mapped_column(
        ForeignKey("annotators.id", ondelete="SET NULL"), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
