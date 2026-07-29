"""JudgeCacheEntry model (M7, §4) — "identical calls are never paid for twice".

§4 fixes the key: ``(judge_config_id + prompt_version, unit_id, variant)``. The
prompt hash rides along as a guard rather than as the key — if the assembled
prompt changed while the version did not (a template restyle that leaked into the
serialization, say), the entry is treated as a miss instead of silently answering
from a prompt nobody sent. That is the difference between a cache and a lie.

Variant is stored as a canonical *string* (``"AB"``, or ``""`` for a template with
no variants) so the uniqueness constraint is a plain btree index instead of a
JSONB comparison whose equality semantics depend on key order.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class JudgeCacheEntry(Base):
    __tablename__ = "judge_cache"
    __table_args__ = (
        Index(
            "uq_judge_cache_key",
            "judge_config_id",
            "prompt_version",
            "unit_id",
            "variant_key",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judge_config_id: Mapped[int] = mapped_column(
        ForeignKey("judge_configs.id", ondelete="CASCADE"), nullable=False
    )
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_id: Mapped[int] = mapped_column(
        ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_key: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
