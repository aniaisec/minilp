"""User model (§4) — access control (roles), distinct from annotators."""

from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin

USER_ROLES = ("admin", "reviewer", "annotator")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'reviewer', 'annotator')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="annotator")
    api_key_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
