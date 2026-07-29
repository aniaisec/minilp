"""M7 judge orchestrator: runs, response cache, webhook deliveries.

Revision ID: d4e6f8a0b2c4
Revises: c3d5e7f9a1b2
Create Date: 2026-07-28

Three tables, no changes to anything existing — which is the point of the
schema-first bet made in M1. ``judge_configs``, ``annotators.kind``,
``labels.cost_usd/tokens_*/cache_hit`` and ``webhooks`` have all been sitting
there since the first migration, so enrolling a model judge needed no
migration-of-migrations and no backfill of live labels.

- ``judge_runs`` — the audit record of one orchestrator invocation (§7.1).
- ``judge_cache`` — §4's "identical calls are never paid for twice", keyed on
  ``(judge_config_id + prompt_version, unit_id, variant)``.
- ``webhook_deliveries`` — what §7.3 promises is auditable: which event went
  where, signed how, and whether it arrived.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d4e6f8a0b2c4"
down_revision: str | None = "c3d5e7f9a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "judge_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("judge_config_id", sa.Integer(), nullable=False),
        sa.Column("annotator_id", sa.Integer(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("stopped_reason", sa.String(length=40), nullable=True),
        sa.Column("slots_attempted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("labels_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'stopped', 'failed')",
            name="ck_judge_runs_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["judge_config_id"], ["judge_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["annotator_id"], ["annotators.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_judge_runs_project_id", "judge_runs", ["project_id"])
    op.create_index("ix_judge_runs_judge_config_id", "judge_runs", ["judge_config_id"])

    op.create_table(
        "judge_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("judge_config_id", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("variant_key", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["judge_config_id"], ["judge_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_judge_cache_unit_id", "judge_cache", ["unit_id"])
    op.create_index(
        "uq_judge_cache_key",
        "judge_cache",
        ["judge_config_id", "prompt_version", "unit_id", "variant_key"],
        unique=True,
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("webhook_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=50), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("signature", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'failed')",
            name="ck_webhook_deliveries_status",
        ),
        sa.ForeignKeyConstraint(["webhook_id"], ["webhooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_deliveries_webhook_id", "webhook_deliveries", ["webhook_id"])
    op.create_index("ix_webhook_deliveries_event", "webhook_deliveries", ["event"])
    op.create_index("ix_webhook_deliveries_project_id", "webhook_deliveries", ["project_id"])


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_index("uq_judge_cache_key", table_name="judge_cache")
    op.drop_table("judge_cache")
    op.drop_table("judge_runs")
