"""Label model (§2.8, §4) — one submitted judgment.

``unit_id`` is denormalized from the slot so a partial unique index can enforce
"at most one valid label per annotator per unit" (not merely per slot)."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Label(Base):
    __tablename__ = "labels"
    __table_args__ = (
        # §4: "Unique partial index preventing two valid labels by the same
        # annotator on the same *unit* (not just slot)."
        Index(
            "uq_labels_annotator_unit_valid",
            "annotator_id",
            "unit_id",
            unique=True,
            postgresql_where="is_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slot_id: Mapped[int] = mapped_column(
        ForeignKey("slots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[int] = mapped_column(
        ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    annotator_id: Mapped[int] = mapped_column(
        ForeignKey("annotators.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cache_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
