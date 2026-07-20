"""Annotator model (§4, principle 2) — humans and model judges are the same
thing to the system, distinguished by ``kind``."""

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin

ANNOTATOR_KINDS = ("human", "model")


class Annotator(TimestampMixin, Base):
    __tablename__ = "annotators"
    __table_args__ = (
        CheckConstraint("kind IN ('human', 'model')", name="ck_annotators_kind"),
        # user_id required for humans; null for model judges.
        CheckConstraint(
            "(kind = 'human' AND user_id IS NOT NULL) OR "
            "(kind = 'model' AND judge_config_id IS NOT NULL)",
            name="ck_annotators_kind_links",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    judge_config_id: Mapped[int | None] = mapped_column(
        ForeignKey("judge_configs.id", ondelete="SET NULL"), nullable=True
    )
    reputation_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # Why the annotator was paused (§6.1) — shown in their report and the admin
    # annotator table, so a pause is explainable rather than mysterious.
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
