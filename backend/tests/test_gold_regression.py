"""M6 — the ``is_gold`` contract, pinned (§6.1, §12 M6 acceptance).

A unit uploaded with ``is_gold: true`` and ``gold_expected`` becomes a gold with
no further ceremony: it is injected at the project's ``gold_ratio``, served in
balance when a gold slot is available, graded on submit, and feeds rolling gold
accuracy and reputation. A project with **no** golds collects uninterrupted.

This behavior has held since M1-M4; M6 adds a UI affordance for marking golds, so
these tests exist to stop the affordance from quietly changing the contract:

    present → served & measured    ·    absent → uninterrupted collection

They also cover the M6 addition: **golds in an appended batch enter measurement
immediately** (§6.1) — you can add a gold to a running project without restarting
it.
"""

import json

from sqlalchemy import select

from app.models import Annotator, Label, Slot, Template, Unit, User
from app.services.assignment import next_task, submit_label
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.quality import gold_accuracy
from app.services.slots.generation import verify_balance
from app.services.templates.seed import seed_templates

# --- helpers ----------------------------------------------------------------


def _annotator(db, email: str) -> Annotator:
    user = User(email=email, role="annotator")
    db.add(user)
    db.flush()
    ann = Annotator(kind="human", user_id=user.id, display_name=email)
    db.add(ann)
    db.flush()
    return ann


def _project(db, name, *, template="image-classification", **kwargs):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == template))
    return create_project(db, name=name, template_id=tmpl.id, **kwargs)


def _rows(n, *, gold=False, expected="cat"):
    out = []
    for i in range(n):
        row = {"payload": {"image_url": f"http://x/{i}.png"}}
        if gold:
            row["is_gold"] = True
            row["gold_expected"] = {"category": expected}
        out.append(row)
    return out


def _ingest(db, project, rows, **kwargs):
    return ingest_units(db, project, parse_jsonl("\n".join(json.dumps(r) for r in rows)), **kwargs)


def _drain(db, annotator, project, answer, limit=50):
    """Label everything available; returns the units seen, in order."""
    seen = []
    for _ in range(limit):
        slot = next_task(db, annotator.id, project.id)
        if slot is None:
            break
        submit_label(db, slot.id, annotator.id, raw=dict(answer))
        seen.append(slot.unit_id)
    return seen


# --- present → served & measured -------------------------------------------


def test_uploading_is_gold_makes_a_gold_with_no_further_configuration(db) -> None:
    project = _project(db, "golds", labels_per_unit=1, gold_ratio=0.5)
    _ingest(db, project, _rows(2, gold=True) + _rows(4))

    units = list(db.scalars(select(Unit).where(Unit.project_id == project.id).order_by(Unit.id)))
    golds = [u for u in units if u.is_gold]
    assert len(golds) == 2
    assert all(u.gold_expected == {"category": "cat"} for u in golds)
    # Golds are ordinary units in every other respect — same slot generation.
    assert all(len(list(db.scalars(select(Slot).where(Slot.unit_id == u.id)))) == 1 for u in units)


def test_a_gold_is_served_and_moves_gold_accuracy(db) -> None:
    """present → served & measured."""
    project = _project(db, "golds", labels_per_unit=1, gold_ratio=0.5)
    _ingest(db, project, _rows(3, gold=True) + _rows(3))
    ann = _annotator(db, "a@x")

    seen = _drain(db, ann, project, {"category": "cat"})
    assert len(seen) == 6

    graded = list(
        db.scalars(
            select(Label).where(Label.annotator_id == ann.id, Label.gold_passed.is_not(None))
        )
    )
    assert len(graded) == 3, "every gold served must be graded"
    assert all(label.gold_passed for label in graded)

    passes, total = gold_accuracy(db, ann.id, window=10)
    assert (passes, total) == (3, 3)


def test_a_wrong_gold_answer_lowers_accuracy_without_telling_the_annotator(db) -> None:
    project = _project(db, "golds", labels_per_unit=1, gold_ratio=0.5)
    _ingest(db, project, _rows(2, gold=True) + _rows(2))
    ann = _annotator(db, "a@x")

    outcomes = []
    for _ in range(4):
        slot = next_task(db, ann.id, project.id)
        if slot is None:
            break
        label = submit_label(db, slot.id, ann.id, raw={"category": "dog"})
        outcomes.append(label.quality.as_dict())

    passes, total = gold_accuracy(db, ann.id, window=10)
    assert (passes, total) == (0, 2), "both golds graded, both failed"
    # §6.1 blinding: even the internal outcome never carries the pass/fail — the
    # API layer narrows this further (see ``_blind_quality``), but the invariant
    # starts here so a future caller can't leak what the pipeline never says.
    for outcome in outcomes:
        assert "gold_passed" not in outcome
        assert set(outcome) >= {"gold_graded", "paused", "labels_voided", "reputation"}


def test_golds_follow_the_variant_rules_like_any_other_unit(db) -> None:
    """§2.7: bias metrics on golds are only comparable if golds are balanced too."""
    project = _project(
        db,
        "sbs",
        template="side-by-side-preference",
        labels_per_unit=2,
        gold_ratio=0.5,
    )
    rows = [
        {
            "payload": {"prompt": "p", "response_a": "a", "response_b": "b"},
            "is_gold": True,
            "gold_expected": {"choice": "A"},
        }
    ]
    _ingest(db, project, rows)
    tmpl = db.get(Template, project.template_id)
    gold = db.scalar(select(Unit).where(Unit.project_id == project.id, Unit.is_gold.is_(True)))
    variants = [s.variant for s in db.scalars(select(Slot).where(Slot.unit_id == gold.id))]
    assert verify_balance(variants, tmpl.schema)


# --- absent → uninterrupted collection --------------------------------------


def test_a_gold_free_project_collects_uninterrupted(db) -> None:
    """absent → uninterrupted collection.

    ``gold_ratio`` is a *preference*, not a requirement: with no golds to inject,
    the assignment engine serves normal units instead of stalling on an empty
    gold pool.
    """
    project = _project(db, "no-golds", labels_per_unit=1, gold_ratio=0.5)
    _ingest(db, project, _rows(6))
    ann = _annotator(db, "a@x")

    seen = _drain(db, ann, project, {"category": "cat"})

    assert len(seen) == 6, "collection must not stall when the gold pool is empty"
    assert (
        db.scalar(select(Unit).where(Unit.project_id == project.id, Unit.is_gold.is_(True))) is None
    )
    graded = list(
        db.scalars(
            select(Label).where(Label.annotator_id == ann.id, Label.gold_passed.is_not(None))
        )
    )
    assert graded == [], "nothing to grade means nothing graded"
    assert gold_accuracy(db, ann.id, window=10) == (0, 0)


# --- M6: golds in an appended batch measure immediately ---------------------


def test_a_gold_added_to_a_live_project_enters_measurement_immediately(db) -> None:
    """§12 M6: "add tasks" appends a batch to a running project; a gold in that
    batch is graded from its first submission — no restart, no re-import."""
    project = _project(db, "growing", labels_per_unit=1, gold_ratio=0.5)
    _ingest(db, project, _rows(2), batch_name="first")
    ann = _annotator(db, "a@x")
    _drain(db, ann, project, {"category": "cat"})
    assert gold_accuracy(db, ann.id, window=10) == (0, 0)

    # Second batch, appended to the live project, carries a gold.
    report = _ingest(db, project, _rows(1, gold=True), batch_name="second")
    assert report.unit_count == 1
    assert report.batch_id is not None

    _drain(db, ann, project, {"category": "cat"})
    assert gold_accuracy(db, ann.id, window=10) == (1, 1)


def test_a_gold_row_without_gold_expected_is_rejected_with_its_row_number(db) -> None:
    """The builder's "mark as gold" affordance has to supply an expectation; a
    gold that grades nothing would silently never measure anything."""
    project = _project(db, "p", labels_per_unit=1)
    rows = [{"payload": {"image_url": "http://x/1.png"}, "is_gold": True}]
    report = _ingest(db, project, rows)
    assert report.unit_count == 0
    assert report.rejected_count == 1
    assert "gold_expected" in report.rows[0].errors[0]


def test_golds_stay_invisible_in_the_served_task(db) -> None:
    """§6.1: nothing the annotator receives distinguishes a gold."""
    project = _project(db, "p", labels_per_unit=1, gold_ratio=0.5)
    _ingest(db, project, _rows(1, gold=True) + _rows(1))
    ann = _annotator(db, "a@x")

    slot = next_task(db, ann.id, project.id)
    unit = db.get(Unit, slot.unit_id)
    # The slot the engine hands out carries no gold marker of any kind.
    assert not hasattr(slot, "is_gold")
    assert unit.payload.keys() == {"image_url"}
