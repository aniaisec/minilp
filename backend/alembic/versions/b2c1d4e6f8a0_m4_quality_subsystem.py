"""M4 quality subsystem: gold outcomes, pause reasons, unit consensus snapshots.

Revision ID: b2c1d4e6f8a0
Revises: fa4559003e71
Create Date: 2026-07-19

Adds the four columns the quality pipeline (§6) writes:

- ``labels.gold_passed``    — graded gold outcome, NULL on normal units. Partial
  index on the non-NULL rows keeps rolling gold accuracy an index-only scan even
  when golds are 10% of a large table.
- ``annotators.pause_reason`` — why assignment was cut off (§6.1).
- ``units.quality``          — last per-key consensus snapshot (§6.4).
- ``units.escalated_at``     — routed to human review (§7.2); partial index because
  escalated units are the rare ones the review queue scans for.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b2c1d4e6f8a0"
down_revision: str | None = "fa4559003e71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("labels", sa.Column("gold_passed", sa.Boolean(), nullable=True))
    op.create_index(
        "ix_labels_gold_passed",
        "labels",
        ["annotator_id", "submitted_at"],
        postgresql_where=sa.text("gold_passed IS NOT NULL"),
    )

    op.add_column("annotators", sa.Column("pause_reason", sa.Text(), nullable=True))

    op.add_column(
        "units", sa.Column("quality", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "units", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_units_escalated_at",
        "units",
        ["escalated_at"],
        postgresql_where=sa.text("escalated_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_units_escalated_at", table_name="units")
    op.drop_column("units", "escalated_at")
    op.drop_column("units", "quality")
    op.drop_column("annotators", "pause_reason")
    op.drop_index("ix_labels_gold_passed", table_name="labels")
    op.drop_column("labels", "gold_passed")
