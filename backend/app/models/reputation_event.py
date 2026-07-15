"""ReputationEvent model (§4, §6.2) — append-only log driving reputation."""

from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin

REPUTATION_EVENT_KINDS = (
    "gold_pass",
    "gold_fail",
    "agreement",
    "bias_flag",
    "speed_flag",
)


class ReputationEvent(TimestampMixin, Base):
    __tablename__ = "reputation_events"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('gold_pass', 'gold_fail', 'agreement', 'bias_flag', 'speed_flag')",
            name="ck_reputation_events_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    annotator_id: Mapped[int] = mapped_column(
        ForeignKey("annotators.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
