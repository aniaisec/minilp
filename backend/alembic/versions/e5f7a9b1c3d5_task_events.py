"""Measurement: task_events — the slot transitions ``labels`` cannot see.

Revision ID: e5f7a9b1c3d5
Revises: d4e6f8a0b2c4
Create Date: 2026-09-10

One new table, nothing existing changes. A label records a task that was
answered; a skip, an exit-to-home or an expired lease reopened the slot and left
no row anywhere. Skip rate, abandonment and lease-to-answer time are the numbers
a labeling study needs about the platform itself, and none of them can be
reconstructed after the fact — so they are logged at the transition.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f7a9b1c3d5"
down_revision: str | None = "d4e6f8a0b2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("slot_id", sa.Integer(), nullable=False),
        sa.Column("annotator_id", sa.Integer(), nullable=True),
        sa.Column("label_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('leased', 'resumed', 'skipped', 'exited', 'released', 'expired', "
            "'submitted')",
            name="ck_task_events_kind",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["slot_id"], ["slots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["annotator_id"], ["annotators.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["label_id"], ["labels.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_events_project_id", "task_events", ["project_id"])
    op.create_index("ix_task_events_slot_id", "task_events", ["slot_id"])
    op.create_index("ix_task_events_annotator_id", "task_events", ["annotator_id"])


def downgrade() -> None:
    op.drop_index("ix_task_events_annotator_id", table_name="task_events")
    op.drop_index("ix_task_events_slot_id", table_name="task_events")
    op.drop_index("ix_task_events_project_id", table_name="task_events")
    op.drop_table("task_events")
