"""JudgeRun model (M7, §7.1) — one orchestrator invocation over a project.

A run is the audit record of "I pointed judge X at project Y": how many slots it
attempted, how many labels it wrote, what it spent, what it hit, and *why it
stopped*. Dry runs are recorded the same way with ``dry_run=True`` and zero cost,
so an estimate and the live run that follows it sit side by side in the history —
which is the only honest way to check whether the estimate was any good.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RUN_STATUSES = ("running", "completed", "stopped", "failed")

# Why a run ended. ``exhausted`` is the happy path: no eligible slots left.
STOP_REASONS = (
    "exhausted",
    "limit",
    "budget_project",
    "budget_daily",
    "budget_tokens",
    "budget_labels",
    "provider_error",
)


class JudgeRun(Base):
    __tablename__ = "judge_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'stopped', 'failed')",
            name="ck_judge_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    judge_config_id: Mapped[int] = mapped_column(
        ForeignKey("judge_configs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    annotator_id: Mapped[int | None] = mapped_column(
        ForeignKey("annotators.id", ondelete="SET NULL"), nullable=True
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    stopped_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    slots_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    labels_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Estimated spend for a dry run (live runs leave this null).
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
