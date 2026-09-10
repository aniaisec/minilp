"""Provision study raters: one user + API key + human annotator each.

There is no user-management API (§5 leaves identity to the deployment), and a
study cannot run with everyone labeling as the demo annotator — per-rater
accuracy, reputation and pause detection are the point. This is the admin-side
tool that fills the gap without adding an endpoint that mints credentials.

    docker compose exec backend python -m app.measure.provision \
        --prefix pilot --count 8 --out /tmp/raters.json

Keys are printed once and never stored in the clear (only their hash, like the
demo admin key). Re-running leaves existing raters alone and reports them
without a key; ``--rotate`` issues fresh keys, which invalidates the old ones.
"""

from __future__ import annotations

import argparse
import json
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotator, User
from app.services.auth.roles import ROLE_RANK, hash_api_key

EMAIL_DOMAIN = "study.local"


def rater_email(prefix: str, index: int) -> str:
    return f"{prefix}-{index:02d}@{EMAIL_DOMAIN}"


def provision_raters(
    db: Session,
    *,
    prefix: str,
    count: int,
    role: str = "annotator",
    rotate: bool = False,
) -> list[dict[str, Any]]:
    """Create (or find) ``count`` raters named ``{prefix}-NN``. Caller commits."""
    if role not in ROLE_RANK:
        raise ValueError(f"role must be one of {sorted(ROLE_RANK)}")
    if count < 1:
        raise ValueError("count must be at least 1")
    out = []
    for index in range(1, count + 1):
        email = rater_email(prefix, index)
        user = db.scalar(select(User).where(User.email == email))
        api_key: str | None = None
        existing = user is not None
        if user is None:
            api_key = secrets.token_urlsafe(24)
            user = User(email=email, role=role, api_key_hash=hash_api_key(api_key))
            db.add(user)
            db.flush()
        elif rotate:
            api_key = secrets.token_urlsafe(24)
            user.api_key_hash = hash_api_key(api_key)
        annotator = db.scalar(
            select(Annotator).where(Annotator.user_id == user.id, Annotator.kind == "human")
        )
        if annotator is None:
            annotator = Annotator(
                kind="human",
                user_id=user.id,
                email=email,
                display_name=f"{prefix}-{index:02d}",
                status="active",
                reputation_score=1.0,
            )
            db.add(annotator)
            db.flush()
        out.append(
            {
                "name": annotator.display_name,
                "email": email,
                "user_id": user.id,
                "annotator_id": annotator.id,
                "api_key": api_key,
                "existing": existing,
            }
        )
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--prefix", required=True, help="rater name prefix, e.g. 'pilot'")
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--role", default="annotator", choices=sorted(ROLE_RANK))
    parser.add_argument("--rotate", action="store_true", help="reissue keys for existing raters")
    parser.add_argument("--out", help="write the roster (with keys) to this JSON file")
    parser.add_argument("--app-url", default="http://localhost:5173")
    args = parser.parse_args(argv)

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        raters = provision_raters(
            db, prefix=args.prefix, count=args.count, role=args.role, rotate=args.rotate
        )
        db.commit()
    finally:
        db.close()

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(raters, fh, indent=2)
    for r in raters:
        if r["api_key"]:
            print(f"{r['name']}  {args.app_url}/?annotator={r['annotator_id']}&key={r['api_key']}")
        else:
            print(f"{r['name']}  (exists — key unchanged; --rotate to reissue)")


if __name__ == "__main__":
    main()
