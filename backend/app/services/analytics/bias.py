"""Variant / order-bias analytics (§9) — reported separately for humans and model
judges, because LLM position bias is a headline research metric.

Four figures, all built on the same positional-answer extraction:

1. **Global variant-preference rate** — P(raw side = the first position) with a
   Wilson CI. ≈ 0.5 is unbiased; a judge that always picks the left panel lands
   near 1.0 with a tight interval.
2. **Per-annotator bias score** — each rater's/judge's split with CI (the same
   ``bias_score`` reputation penalizes on, §6.2), so the dashboard and the
   annotator report never disagree.
3. **Per-unit order sensitivity** — does the canonical winner flip across variant
   values? High-flip units are ambiguous or bias-sensitive and worth extra labels.
4. **Bias-adjusted outcomes** — canonical-value distribution per key, raw and
   stratified by variant value.

"Positional" answers are raw values in the left/right family; a template without
positional inputs yields empty humans/judges blocks rather than a fabricated 0.5.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotator, Label, Project, Slot, Unit
from app.services.analytics.stats import bias_score, token, wilson_interval
from app.services.quality.matching import _hashable

# Raw positional tokens (mirror reputation._LEFT / _RIGHT). "first" == the panel
# shown on the left / choice A; "second" == the right panel / choice B.
_FIRST = {"left", "a", "first"}
_SECOND = {"right", "b", "second"}


def _side(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if token in _FIRST:
        return "first"
    if token in _SECOND:
        return "second"
    return None


def _positional_rows(
    db: Session, project_id: int, kind: str
) -> list[tuple[int, int, dict[str, Any], dict[str, Any], dict[str, Any] | None]]:
    """(unit_id, annotator_id, raw, value, variant) for valid labels of one kind
    on slots that carry a variant."""
    stmt = (
        select(Label.unit_id, Label.annotator_id, Label.raw, Label.value, Slot.variant)
        .join(Unit, Label.unit_id == Unit.id)
        .join(Slot, Label.slot_id == Slot.id)
        .join(Annotator, Label.annotator_id == Annotator.id)
        .where(
            Unit.project_id == project_id,
            Label.is_valid.is_(True),
            Annotator.kind == kind,
            Slot.variant.is_not(None),
        )
    )
    return [tuple(r) for r in db.execute(stmt).all()]


def _group_bias(rows: list[tuple[int, int, dict, dict, dict | None]]) -> dict[str, Any]:
    """Global + per-annotator preference for one annotator kind."""
    first = second = 0
    per_annotator: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for _unit_id, annotator_id, raw, _value, _variant in rows:
        for val in (raw or {}).values():
            side = _side(val)
            if side == "first":
                first += 1
                per_annotator[annotator_id][0] += 1
            elif side == "second":
                second += 1
                per_annotator[annotator_id][1] += 1

    total = first + second
    interval = wilson_interval(first, total)
    annotators = [
        {
            "annotator_id": aid,
            "first": f,
            "second": s,
            "preference": wilson_interval(f, f + s).as_dict(),
            "bias_score": (round(bias_score(f, s), 4) if bias_score(f, s) is not None else None),
        }
        for aid, (f, s) in sorted(per_annotator.items())
    ]
    return {
        "n_positional_labels": total,
        "prefer_first_rate": interval.as_dict(),
        "bias_score": round(bias_score(first, second), 4) if total else None,
        "annotators": annotators,
    }


def _order_sensitivity(db: Session, project_id: int) -> dict[str, Any]:
    """Per-unit: does the canonical winner flip across variant values? (§9)

    For each unit and each key, the winner within a variant value is the plurality
    canonical answer; a unit's key is "flipped" if two variant values resolve to
    different winners. Uses all valid labels (humans and judges together) — order
    sensitivity is a property of the item, not the rater pool."""
    rows = db.execute(
        select(Label.unit_id, Label.value, Slot.variant)
        .join(Unit, Label.unit_id == Unit.id)
        .join(Slot, Label.slot_id == Slot.id)
        .where(
            Unit.project_id == project_id,
            Label.is_valid.is_(True),
            Slot.variant.is_not(None),
        )
    ).all()

    # unit -> key -> variant_json -> Counter(canonical value)
    tree: dict[int, dict[str, dict[str, Counter]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(Counter))
    )
    for unit_id, value, variant in rows:
        vkey = _hashable(variant)
        for key, val in (value or {}).items():
            tree[unit_id][key][vkey][_hashable(val)] += 1

    units = []
    flipped_units = 0
    for unit_id in sorted(tree):
        any_flip = False
        keys_out = {}
        for key, by_variant in tree[unit_id].items():
            if len(by_variant) < 2:
                continue  # need at least two variant values to detect a flip
            winners = {vkey: counter.most_common(1)[0][0] for vkey, counter in by_variant.items()}
            flipped = len(set(winners.values())) > 1
            keys_out[key] = {"flipped": flipped, "winners_by_variant": len(set(winners.values()))}
            any_flip = any_flip or flipped
        if not keys_out:
            continue
        if any_flip:
            flipped_units += 1
        units.append({"unit_id": unit_id, "flipped": any_flip, "keys": keys_out})

    measurable = len(units)
    return {
        "measurable_units": measurable,
        "flipped_units": flipped_units,
        "flip_rate": round(flipped_units / measurable, 4) if measurable else None,
        "units": units,
    }


def _adjusted_outcomes(db: Session, project_id: int) -> dict[str, Any]:
    """Canonical-value distribution per key, overall and stratified by variant
    value — win rates 'raw and stratified by variant' (§9)."""
    rows = db.execute(
        select(Label.value, Slot.variant)
        .join(Unit, Label.unit_id == Unit.id)
        .join(Slot, Label.slot_id == Slot.id)
        .where(Unit.project_id == project_id, Label.is_valid.is_(True))
    ).all()

    overall: dict[str, Counter] = defaultdict(Counter)
    by_variant: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for value, variant in rows:
        vkey = token(variant) if variant else "_none"
        for key, val in (value or {}).items():
            overall[key][token(val)] += 1
            by_variant[key][vkey][token(val)] += 1

    keys = {}
    for key in sorted(overall):
        keys[key] = {
            "overall": dict(overall[key]),
            "by_variant": {vk: dict(c) for vk, c in by_variant[key].items()},
        }
    return {"keys": keys}


def project_bias(db: Session, project_id: int) -> dict[str, Any]:
    """Full §9 bias report for ``GET /projects/{id}/analytics/bias``."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")

    return {
        "project_id": project_id,
        "humans": _group_bias(_positional_rows(db, project_id, "human")),
        "judges": _group_bias(_positional_rows(db, project_id, "model")),
        "order_sensitivity": _order_sensitivity(db, project_id),
        "adjusted_outcomes": _adjusted_outcomes(db, project_id),
    }
