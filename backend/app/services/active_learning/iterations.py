"""The iteration eval curve (§8 step 4/5) — "gold accuracy and
agreement-vs-final-labels become the eval curve; the dashboard plots
student-model calibration across iterations."

Every number here is read, not computed fresh: gold accuracy is
``quality.reputation.gold_accuracy`` (§6.1/§6.2) against the *same* rolling
window the reputation engine itself uses, spend is
``judges.budget.judge_spend`` (§7.1) reading straight off ``labels``, and an
iteration is just a ``judge_configs`` row grouped by name and ordered by
``prompt_version`` — the version counter M7 already keeps immutable per
version (§2.5). ``agreement_vs_final`` is the one genuinely new metric: how
often this checkpoint's answer matches the unit's *decided* answer in
``final_labels`` (§7.2), which — unlike peer agreement — accounts for a human
review overriding the ensemble (§7.2's whole point).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Annotator, FinalLabel, Label, Project, Template, Unit
from app.services.judges.budget import judge_spend
from app.services.judges.configs import list_judge_configs
from app.services.quality.matching import input_types, rule_for, values_match
from app.services.quality.reputation import gold_accuracy

__all__ = ["agreement_vs_final", "iteration_curve"]

_MISSING = object()


def agreement_vs_final(db: Session, annotator_id: int, project_id: int) -> tuple[int, int]:
    """(agreements, comparisons) of this annotator's answers against the
    project's *decided* labels — only units that have finalized so far."""
    project = db.get(Project, project_id)
    if project is None:
        return 0, 0
    template = db.get(Template, project.template_id) if project.template_id else None
    types = input_types(template.schema if template else None)

    rows = db.execute(
        select(Label.value, FinalLabel.value)
        .join(Unit, Label.unit_id == Unit.id)
        .join(FinalLabel, FinalLabel.unit_id == Unit.id)
        .where(
            Label.annotator_id == annotator_id,
            Label.is_valid.is_(True),
            Unit.project_id == project_id,
        )
    ).all()

    agreements = comparisons = 0
    for mine, decided in rows:
        for key, expected in (decided or {}).items():
            actual = (mine or {}).get(key, _MISSING)
            if actual is _MISSING:
                continue
            rule = rule_for(project.agreement, key, types.get(key))
            comparisons += 1
            if values_match(actual, expected, rule):
                agreements += 1
    return agreements, comparisons


def _human_minutes(db: Session, project_id: int) -> float:
    """Human labor spent on this project so far — the loop-metrics counterpart
    to a judge's ``cost_usd`` (§8 step 5 "spend, human minutes, ... per
    iteration"). Reported at the project level: unlike a judge, a human rater
    isn't versioned, so there is no per-iteration split to attribute it to."""
    total_ms = db.scalar(
        select(func.coalesce(func.sum(Label.latency_ms), 0))
        .select_from(Label)
        .join(Unit, Label.unit_id == Unit.id)
        .join(Annotator, Label.annotator_id == Annotator.id)
        .where(Unit.project_id == project_id, Annotator.kind == "human", Label.is_valid.is_(True))
    )
    return round((total_ms or 0) / 60000.0, 2)


def _point(db: Session, project_id: int, config) -> dict[str, Any]:
    annotator = db.scalar(
        select(Annotator).where(Annotator.judge_config_id == config.id, Annotator.kind == "model")
    )
    gold: dict[str, Any] = {"passes": 0, "total": 0, "rate": None}
    agree: dict[str, Any] = {"agreements": 0, "comparisons": 0, "rate": None}
    spend: dict[str, Any] | None = None
    label_count = 0

    if annotator is not None:
        passes, total = gold_accuracy(db, annotator.id, project_id=project_id, window=10_000)
        rate = round(passes / total, 4) if total else None
        gold = {"passes": passes, "total": total, "rate": rate}
        agreements, comparisons = agreement_vs_final(db, annotator.id, project_id)
        agree = {
            "agreements": agreements,
            "comparisons": comparisons,
            "rate": round(agreements / comparisons, 4) if comparisons else None,
        }
        s = judge_spend(db, project_id, annotator.id)
        spend = {"cost_usd": s.cost_usd, "tokens": s.tokens, "labels": s.labels}
        label_count = s.labels

    return {
        "judge_config_id": config.id,
        "iteration": config.prompt_version,
        "provider": config.provider,
        "model_id": config.model_id,
        "annotator_id": annotator.id if annotator is not None else None,
        "enrolled": annotator is not None,
        "gold_accuracy": gold,
        "agreement_vs_final": agree,
        "spend": spend,
        "label_count": label_count,
        "created_at": config.created_at.isoformat() if config.created_at else None,
    }


def iteration_curve(db: Session, project_id: int, name: str) -> dict[str, Any]:
    """The eval curve for one judge-config name — its version history read as
    AL iterations, oldest first (§5 ``GET
    /projects/{id}/active-learning/iterations``)."""
    if db.get(Project, project_id) is None:
        raise ValueError(f"project {project_id} not found")

    configs = sorted(list_judge_configs(db, name=name), key=lambda c: c.prompt_version)
    if not configs:
        raise ValueError(f"no judge config named '{name}'")

    return {
        "project_id": project_id,
        "name": name,
        "iterations": [_point(db, project_id, config) for config in configs],
        "human_minutes": _human_minutes(db, project_id),
    }
