"""FinalLabel model (§4) — the decided label for a unit, with provenance."""

from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin

FINAL_LABEL_METHODS = ("auto_consensus", "human_approved", "human_override", "expert")


class FinalLabel(TimestampMixin, Base):
    __tablename__ = "final_labels"
    __table_args__ = (
        CheckConstraint(
            "method IN ('auto_consensus', 'human_approved', 'human_override', 'expert')",
            name="ck_final_labels_method",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(
        ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
