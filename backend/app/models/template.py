"""Template model — a versioned JSON document (§2.1, §4).

Immutable per (name, version): a schema-affecting edit produces a new row with an
incremented version rather than mutating an existing one.
"""

from typing import Any

from sqlalchemy import CheckConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin

TEMPLATE_KINDS = ("builtin", "custom")


class Template(TimestampMixin, Base):
    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_templates_name_version"),
        CheckConstraint("kind IN ('builtin', 'custom')", name="ck_templates_kind"),
        CheckConstraint("version >= 1", name="ck_templates_version_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="custom")
    schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Example unit payload for the template gallery / project wizard (M5, §11).
    # Presentation metadata, not part of the versioned schema — editing it never
    # bumps the version and is allowed on builtins. NULL means "no saved sample;
    # generate one from the schema on demand".
    sample: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
