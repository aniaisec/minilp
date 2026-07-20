"""Unit model (§4) — one labelable item, carrying its JSON payload, priority,
and optional gold expectation.

``quality``/``escalated_at`` are written by the M4 consensus evaluator (§6.4):
the former caches the last per-key consensus snapshot (so the unit browser and
progress view can read it without recomputing), the latter marks a unit routed to
human review (§7.2 — the queue itself lands in M8)."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin

UNIT_STATUSES = ("pending", "in_progress", "labeled", "finalized")


class Unit(TimestampMixin, Base):
    __tablename__ = "units"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'labeled', 'finalized')",
            name="ck_units_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_gold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gold_expected: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
