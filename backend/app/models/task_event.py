"""TaskEvent model — append-only log of what happened to a leased slot.

``labels`` records the outcome of the tasks that were answered. Everything else
— the skip, the exit-to-home, the lease that quietly expired — used to leave no
trace: ``reopen_slot`` put the slot back in the pool and the evidence went with
it. Measuring the platform needs those too (skip rate, abandonment, time from
lease to answer), so the assignment engine writes one row per transition.

Kinds:
    leased     next_task handed out a new slot
    resumed    next_task returned a slot the annotator already held (reload)
    skipped    the annotator pressed skip
    exited     the annotator left the project (exit-to-home)
    released   a judge worker returned a slot it could not or would not answer
    expired    the lease ran out and the sweeper reclaimed it
    submitted  a label landed (``label_id`` points at it)
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

TASK_EVENT_KINDS = (
    "leased",
    "resumed",
    "skipped",
    "exited",
    "released",
    "expired",
    "submitted",
)


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('leased', 'resumed', 'skipped', 'exited', 'released', 'expired', "
            "'submitted')",
            name="ck_task_events_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), nullable=False)
    slot_id: Mapped[int] = mapped_column(
        ForeignKey("slots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    annotator_id: Mapped[int | None] = mapped_column(
        ForeignKey("annotators.id", ondelete="SET NULL"), nullable=True, index=True
    )
    label_id: Mapped[int | None] = mapped_column(
        ForeignKey("labels.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Written by the engine from its own clock rather than ``now()``: Postgres'
    # ``now()`` is the transaction start, so a judge run that leases and submits
    # a hundred slots in one request would log them all at the same instant.
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
