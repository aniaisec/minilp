"""Batch model (§4) — one row per bulk upload."""

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin


class Batch(TimestampMixin, Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
