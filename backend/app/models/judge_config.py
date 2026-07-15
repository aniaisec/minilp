"""JudgeConfig model (§4, §7.1) — provider + model + params + versioned prompt
+ budget caps. Immutable per prompt version. Exercised from M7."""

from typing import Any

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin


class JudgeConfig(TimestampMixin, Base):
    __tablename__ = "judge_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    budget: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
