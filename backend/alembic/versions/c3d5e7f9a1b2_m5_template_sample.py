"""M5 template gallery: saved sample payload per template.

Revision ID: c3d5e7f9a1b2
Revises: b2c1d4e6f8a0
Create Date: 2026-07-23

Adds ``templates.sample`` — an example unit payload the template gallery previews
and the project wizard prefills (§11). It is presentation metadata, not part of
the versioned ``schema`` (whose JSON Schema is ``additionalProperties: false``),
so a saved sample can live on builtins and custom templates alike without touching
the immutability of the schema itself.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c3d5e7f9a1b2"
down_revision: str | None = "b2c1d4e6f8a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "templates",
        sa.Column("sample", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("templates", "sample")
