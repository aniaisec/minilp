"""Shared FastAPI dependencies — authentication + role gating (§5).

Usage in a router::

    @router.post("", dependencies=[Depends(require_admin)])
    def create_project(...): ...

or to receive the resolved user::

    def next_task(user: User = Depends(require_annotator)): ...
"""

from collections.abc import Callable

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.services.auth.roles import hash_api_key, role_allowed


def _extract_key(authorization: str | None, x_api_key: str | None) -> str | None:
    """Pull the raw API key from ``Authorization: Bearer <key>`` or ``X-API-Key``."""
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        # Also accept a bare token in the Authorization header.
        if len(parts) == 1:
            return parts[0].strip()
    return None


def get_current_user(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated ``User`` from the presented API key, or 401."""
    key = _extract_key(authorization, x_api_key)
    if not key:
        raise HTTPException(status_code=401, detail="missing API key")
    user = db.scalar(select(User).where(User.api_key_hash == hash_api_key(key)))
    if user is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    return user


def require_roles(*allowed: str) -> Callable[..., User]:
    """Build a dependency that admits only the given roles (rank-inclusive)."""
    allowed_set = set(allowed)

    def _dep(user: User = Depends(get_current_user)) -> User:
        if not role_allowed(user.role, allowed_set):
            raise HTTPException(
                status_code=403,
                detail=f"role '{user.role}' not permitted (requires one of {sorted(allowed_set)})",
            )
        return user

    return _dep


# Common gates. Rank-inclusive: require_annotator also admits reviewer/admin.
require_admin = require_roles("admin")
require_reviewer = require_roles("reviewer")
require_annotator = require_roles("annotator")
