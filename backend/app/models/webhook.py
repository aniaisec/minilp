"""Webhook model (§4, §7.3). Registered per project or instance-wide
(null project_id). Exercised from M7/M8."""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin

WEBHOOK_EVENTS = (
    "budget.cap_reached",
    "gold.accuracy_dropped",
    "review.queue_backlog",
    "project.completed",
)


class Webhook(TimestampMixin, Base):
    __tablename__ = "webhooks"
    __table_args__ = (
        CheckConstraint(
            "event IN ('budget.cap_reached', 'gold.accuracy_dropped', "
            "'review.queue_backlog', 'project.completed')",
            name="ck_webhooks_event",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    target_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(200), nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
