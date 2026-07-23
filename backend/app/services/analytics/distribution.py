"""Label-distribution analytics (§11 admin dashboard charts).

Per input key, the distribution of canonical answers — split by annotator kind so
a human/judge divergence is visible at a glance — plus overall counts. Distinct
from bias (§9, which is about *positional* raw answers) and from consensus (§6.4,
which is per-unit): this is the population-level "what did people actually pick".
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotator, Label, Project, Unit
from app.services.analytics.stats import token


def project_distribution(db: Session, project_id: int) -> dict[str, Any]:
    """Canonical-value histogram per key, overall and per annotator kind."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")

    rows = db.execute(
        select(Annotator.kind, Label.value)
        .join(Unit, Label.unit_id == Unit.id)
        .join(Annotator, Label.annotator_id == Annotator.id)
        .where(Unit.project_id == project_id, Label.is_valid.is_(True))
    ).all()

    overall: dict[str, Counter] = defaultdict(Counter)
    by_kind: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for kind, value in rows:
        for key, val in (value or {}).items():
            tok = token(val)
            overall[key][tok] += 1
            by_kind[key][kind][tok] += 1

    keys = {}
    for key in sorted(overall):
        total = sum(overall[key].values())
        keys[key] = {
            "total": total,
            "overall": dict(overall[key]),
            "by_kind": {kind: dict(c) for kind, c in by_kind[key].items()},
        }
    return {"project_id": project_id, "keys": keys}
