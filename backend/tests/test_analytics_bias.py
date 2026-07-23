"""Variant/order-bias analytics against controlled fixtures (§9, M5).

Side-by-side is the only gallery template with variants, so bias is exercised
there. Canonicalization maps a raw side to the item in that slot's panel order
(``variant['panel_order'][0]`` for a Left click), so an annotator who *always*
clicks left produces a maximal preference rate AND a canonical winner that flips
between the AB and BA presentations — the two things §9 measures.
"""

import json

import pytest
from sqlalchemy import select

from app.models import Annotator, Template, User
from app.services.analytics.bias import _side, project_bias
from app.services.assignment import next_task, submit_label
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.templates.seed import seed_templates


def _annotator(db, email):
    user = User(email=email, role="annotator")
    db.add(user)
    db.flush()
    ann = Annotator(kind="human", user_id=user.id, display_name=email)
    db.add(ann)
    db.flush()
    return ann


def _sbs_project(db, name, **kwargs):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == "side-by-side-preference"))
    return create_project(db, name=name, template_id=tmpl.id, **kwargs)


def _ingest(db, project, n):
    rows = [
        {"payload": {"prompt": f"p{i}", "response_a": "a", "response_b": "b"}} for i in range(n)
    ]
    return ingest_units(db, project, parse_jsonl("\n".join(json.dumps(r) for r in rows)))


def _label_all(db, annotators, project, raw, cap=100):
    i = 0
    filled = 0
    while filled < cap:
        ann = annotators[i % len(annotators)]
        slot = next_task(db, ann.id, project.id)
        if slot is None:
            i += 1
            if i > cap * 2:
                break
            continue
        submit_label(db, slot.id, ann.id, raw=raw)
        filled += 1
        i += 1
    return filled


def test_side_token_families():
    assert _side("Left") == "first"
    assert _side("a") == "first"
    assert _side("Right") == "second"
    assert _side("B") == "second"
    assert _side("Tie") is None
    assert _side(3) is None


def test_always_left_gives_max_preference_and_bias(db):
    project = _sbs_project(db, "left", labels_per_unit=2, gold_ratio=0.0)
    a1, a2 = _annotator(db, "l1@x"), _annotator(db, "l2@x")
    _ingest(db, project, 2)
    _label_all(db, [a1, a2], project, {"choice": "Left"})

    bias = project_bias(db, project.id)
    humans = bias["humans"]
    # 4 positional labels, all "first" → estimate 1.0, Wilson CI stays within [0,1].
    assert humans["n_positional_labels"] == 4
    assert humans["prefer_first_rate"]["estimate"] == 1.0
    assert humans["prefer_first_rate"]["ci_low"] < 1.0  # lower bound reflects small n
    assert humans["prefer_first_rate"]["ci_high"] <= 1.0
    assert humans["bias_score"] == 1.0
    # Per-annotator rows present, each maximally biased.
    assert {r["annotator_id"] for r in humans["annotators"]} == {a1.id, a2.id}
    assert all(r["bias_score"] == 1.0 for r in humans["annotators"])
    # No model judges enrolled yet (M7) → empty block, not a fabricated 0.5.
    assert bias["judges"]["n_positional_labels"] == 0
    assert bias["judges"]["bias_score"] is None


def test_order_sensitivity_flags_a_flipping_unit(db):
    project = _sbs_project(db, "flip", labels_per_unit=2, gold_ratio=0.0)
    a1, a2 = _annotator(db, "f1@x"), _annotator(db, "f2@x")
    _ingest(db, project, 2)
    _label_all(db, [a1, a2], project, {"choice": "Left"})

    bias = project_bias(db, project.id)
    order = bias["order_sensitivity"]
    # Each unit has one AB slot and one BA slot; always-Left → winner "A" under AB,
    # "B" under BA → the canonical winner flips on every measurable unit.
    assert order["measurable_units"] == 2
    assert order["flipped_units"] == 2
    assert order["flip_rate"] == 1.0
    assert all(u["flipped"] for u in order["units"])


def test_balanced_left_right_is_unbiased(db):
    """A rater who splits 50/50 lands near 0.5 preference and ~0 bias."""
    project = _sbs_project(db, "even", labels_per_unit=2, gold_ratio=0.0)
    a1, a2 = _annotator(db, "b1@x"), _annotator(db, "b2@x")
    _ingest(db, project, 2)
    # a1 always Left, a2 always Right → 2 first + 2 second overall.
    for _ in range(4):
        slot = next_task(db, a1.id, project.id)
        if slot is None:
            break
        submit_label(db, slot.id, a1.id, raw={"choice": "Left"})
    # a2 fills the remainder with Right.
    while True:
        slot = next_task(db, a2.id, project.id)
        if slot is None:
            break
        submit_label(db, slot.id, a2.id, raw={"choice": "Right"})

    humans = project_bias(db, project.id)["humans"]
    assert humans["prefer_first_rate"]["estimate"] == pytest.approx(0.5)
    assert humans["bias_score"] == pytest.approx(0.0)


def test_adjusted_outcomes_report_canonical_distribution(db):
    project = _sbs_project(db, "outcomes", labels_per_unit=2, gold_ratio=0.0)
    a1, a2 = _annotator(db, "o1@x"), _annotator(db, "o2@x")
    _ingest(db, project, 2)
    _label_all(db, [a1, a2], project, {"choice": "Left"})

    adjusted = project_bias(db, project.id)["adjusted_outcomes"]["keys"]["choice"]
    # Always-Left resolves to items A and B equally (once per variant value).
    assert sum(adjusted["overall"].values()) == 4
    assert set(adjusted["overall"]) == {"A", "B"}
