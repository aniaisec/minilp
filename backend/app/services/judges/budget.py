"""Budget caps (§7.1) — the hard stop that makes an unattended run safe.

Spend is read back from ``labels`` (``cost_usd``, ``tokens_in``, ``tokens_out``)
rather than accumulated in a counter somewhere. That is deliberate: the labels
table is the thing that actually exists after a crash, so a cap computed from it
holds across process restarts, concurrent runs and manual re-runs. A counter in
memory would reset exactly when you least want it to.

Caps are **checked before each call and re-checked after** (§7.1 "hard-stop +
alert"). Checking only before would let a run overshoot by one call; checking
only after would let it overshoot by one call *and* pay for it. The `budget.
cap_reached` webhook fires once per run, at the moment the run stops.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Annotator, JudgeConfig, Label, Unit


@dataclass(frozen=True)
class Spend:
    """What a judge has cost on a project, all-time and in the last 24h."""

    cost_usd: float = 0.0
    daily_usd: float = 0.0
    tokens: int = 0
    labels: int = 0
    cache_hits: int = 0

    def plus(self, *, cost: float = 0.0, tokens: int = 0, labels: int = 0, hits: int = 0) -> Spend:
        return Spend(
            cost_usd=round(self.cost_usd + cost, 6),
            daily_usd=round(self.daily_usd + cost, 6),
            tokens=self.tokens + tokens,
            labels=self.labels + labels,
            cache_hits=self.cache_hits + hits,
        )


@dataclass(frozen=True)
class BudgetStatus:
    ok: bool
    reason: str | None = None
    detail: dict[str, Any] | None = None


def judge_spend(
    db: Session,
    project_id: int,
    annotator_id: int,
    *,
    now: datetime | None = None,
) -> Spend:
    """Read a judge's spend on a project straight out of its labels."""
    now = now or datetime.now(UTC)
    since = now - timedelta(days=1)

    base = (
        select(
            func.coalesce(func.sum(Label.cost_usd), 0.0),
            func.coalesce(func.sum(Label.tokens_in + Label.tokens_out), 0),
            func.count(Label.id),
            func.count(Label.id).filter(Label.cache_hit.is_(True)),
        )
        .select_from(Label)
        .join(Unit, Label.unit_id == Unit.id)
        .where(Label.annotator_id == annotator_id, Unit.project_id == project_id)
    )
    cost, tokens, labels, hits = db.execute(base).one()
    daily = db.scalar(
        select(func.coalesce(func.sum(Label.cost_usd), 0.0))
        .select_from(Label)
        .join(Unit, Label.unit_id == Unit.id)
        .where(
            Label.annotator_id == annotator_id,
            Unit.project_id == project_id,
            Label.submitted_at >= since,
        )
    )
    return Spend(
        cost_usd=round(float(cost or 0.0), 6),
        daily_usd=round(float(daily or 0.0), 6),
        tokens=int(tokens or 0),
        labels=int(labels or 0),
        cache_hits=int(hits or 0),
    )


def check_budget(budget: dict[str, Any] | None, spend: Spend) -> BudgetStatus:
    """Is there room for another call? Pure — the unit-testable half."""
    if not budget:
        return BudgetStatus(True)

    project_cap = budget.get("project_usd")
    if project_cap is not None and spend.cost_usd >= project_cap:
        return BudgetStatus(
            False,
            "budget_project",
            {"cap_usd": project_cap, "spent_usd": spend.cost_usd, "scope": "project"},
        )
    daily_cap = budget.get("daily_usd")
    if daily_cap is not None and spend.daily_usd >= daily_cap:
        return BudgetStatus(
            False,
            "budget_daily",
            {"cap_usd": daily_cap, "spent_usd": spend.daily_usd, "scope": "day"},
        )
    token_cap = budget.get("max_tokens")
    if token_cap is not None and spend.tokens >= token_cap:
        return BudgetStatus(
            False,
            "budget_tokens",
            {"cap_tokens": token_cap, "tokens": spend.tokens, "scope": "project"},
        )
    label_cap = budget.get("max_labels")
    if label_cap is not None and spend.labels >= label_cap:
        return BudgetStatus(
            False,
            "budget_labels",
            {"cap_labels": label_cap, "labels": spend.labels, "scope": "project"},
        )
    return BudgetStatus(True)


def project_costs(db: Session, project_id: int) -> dict[str, Any]:
    """Judge spend, cache-hit rate and $/label for a project (§5 ``/analytics/costs``).

    Human labels are counted but contribute no cost — which is the point of
    showing them side by side: ``$/label`` for the judge column against the
    volume the humans carried is the number that decides the next run's K.
    """
    rows = db.execute(
        select(
            Annotator.id,
            Annotator.display_name,
            Annotator.kind,
            Annotator.judge_config_id,
            func.count(Label.id),
            func.coalesce(func.sum(Label.cost_usd), 0.0),
            func.coalesce(func.sum(Label.tokens_in), 0),
            func.coalesce(func.sum(Label.tokens_out), 0),
            func.count(Label.id).filter(Label.cache_hit.is_(True)),
            func.avg(Label.latency_ms),
        )
        .select_from(Label)
        .join(Unit, Label.unit_id == Unit.id)
        .join(Annotator, Label.annotator_id == Annotator.id)
        .where(Unit.project_id == project_id, Label.is_valid.is_(True))
        .group_by(Annotator.id)
        .order_by(Annotator.id)
    ).all()

    judges: list[dict[str, Any]] = []
    totals = {"labels": 0, "cost_usd": 0.0, "tokens": 0, "cache_hits": 0, "judge_labels": 0}
    for (
        annotator_id,
        display_name,
        kind,
        config_id,
        labels,
        cost,
        tok_in,
        tok_out,
        hits,
        latency,
    ) in rows:
        cost = round(float(cost or 0.0), 6)
        totals["labels"] += int(labels)
        totals["cost_usd"] = round(totals["cost_usd"] + cost, 6)
        totals["tokens"] += int(tok_in or 0) + int(tok_out or 0)
        if kind != "model":
            continue
        totals["cache_hits"] += int(hits or 0)
        totals["judge_labels"] += int(labels)
        config = db.get(JudgeConfig, config_id) if config_id else None
        judges.append(
            {
                "annotator_id": annotator_id,
                "display_name": display_name,
                "judge_config_id": config_id,
                "provider": config.provider if config else None,
                "model_id": config.model_id if config else None,
                "prompt_version": config.prompt_version if config else None,
                "labels": int(labels),
                "cost_usd": cost,
                "tokens_in": int(tok_in or 0),
                "tokens_out": int(tok_out or 0),
                "cache_hits": int(hits or 0),
                "cache_hit_rate": round(int(hits or 0) / labels, 4) if labels else None,
                "cost_per_label": round(cost / labels, 6) if labels else None,
                "avg_latency_ms": round(float(latency), 1) if latency is not None else None,
                "budget": config.budget if config else None,
            }
        )

    judge_labels = totals["judge_labels"]
    return {
        "project_id": project_id,
        "judges": judges,
        "totals": {
            **totals,
            "human_labels": totals["labels"] - judge_labels,
            "cache_hit_rate": (
                round(totals["cache_hits"] / judge_labels, 4) if judge_labels else None
            ),
            "cost_per_judge_label": (
                round(totals["cost_usd"] / judge_labels, 6) if judge_labels else None
            ),
        },
    }
