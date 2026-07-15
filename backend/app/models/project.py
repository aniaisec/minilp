"""Project model (§4). Carries overlap (labels_per_unit), agreement policy,
guidelines, gold ratio, leasing, min reputation, and the routing pipeline."""

from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("labels_per_unit >= 1", name="ck_projects_labels_per_unit_positive"),
        CheckConstraint(
            "max_labels_per_unit >= labels_per_unit",
            name="ck_projects_max_labels_ge_labels",
        ),
        CheckConstraint("gold_ratio >= 0 AND gold_ratio <= 1", name="ck_projects_gold_ratio_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("templates.id", ondelete="RESTRICT"), nullable=False
    )
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    guidelines_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    labels_per_unit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_labels_per_unit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    agreement: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    gold_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)
    lease_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    min_reputation: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pipeline: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
