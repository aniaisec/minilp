"""Assignment engine (M2, §6.4) — DB-backed against real PostgreSQL.

Covers: leasing + annotator-unit exclusion, submit/fill + unit status, skip &
sweeper reopening with variant retained, gold injection ratio, priority ordering,
and void/requeue. Concurrency (SKIP LOCKED, no double-assignment) lives in
``test_concurrency.py``.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Annotator, Label, Slot, Template, Unit, User
from app.services.assignment import (
    AssignmentError,
    next_task,
    should_serve_gold,
    skip_task,
    submit_label,
    sweep_expired_leases,
    void_unit,
)
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
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


def _project(db, name, *, k=1, gold_ratio=0.0, lease_minutes=30, variant=False):
    seed_templates(db)
    tname = "side-by-side-preference" if variant else "text-sentiment"
    tmpl = db.scalar(select(Template).where(Template.name == tname))
    return create_project(
        db,
        name=name,
        template_id=tmpl.id,
        labels_per_unit=k,
        gold_ratio=gold_ratio,
        lease_minutes=lease_minutes,
    )


def _ingest_sentiment(db, project, n_regular=0, n_gold=0, priority=0):
    lines = []
    for i in range(n_regular):
        lines.append(f'{{"payload": {{"text": "u{i}"}}, "priority": {priority}}}')
    for i in range(n_gold):
        lines.append(
            f'{{"payload": {{"text": "g{i}"}}, "is_gold": true, '
            f'"gold_expected": {{"sentiment": "positive"}}}}'
        )
    return ingest_units(db, project, parse_jsonl("\n".join(lines)))


# --- pure gold-injection rule -----------------------------------------------


def test_should_serve_gold_deficit_rule() -> None:
    assert should_serve_gold(0, 0, 0.0) is False  # ratio 0 never injects
    assert should_serve_gold(0, 0, 1.0) is True  # ratio 1 always
    # ratio 0.1: first gold falls on the 10th task, none before.
    assert should_serve_gold(0, 0, 0.1) is False
    assert should_serve_gold(9, 0, 0.1) is True
    assert should_serve_gold(10, 1, 0.1) is False


# --- leasing + exclusion ----------------------------------------------------


def test_fresh_units_are_pending_and_only_leasing_moves_them(db) -> None:
    """The lifecycle the admin sees: uploaded units start ``pending`` with ``open``
    slots; a unit only becomes ``in_progress`` once the assignment engine leases a
    slot — never merely by existing. (Regression: a viewer leasing a task is what
    flips the status, and that must be the *only* thing that does.)"""
    proj = _project(db, "lifecycle", k=1)
    _ingest_sentiment(db, proj, n_regular=2)

    units = db.scalars(select(Unit).where(Unit.project_id == proj.id)).all()
    assert {u.status for u in units} == {"pending"}
    slots = db.scalars(
        select(Slot).join(Unit, Slot.unit_id == Unit.id).where(Unit.project_id == proj.id)
    ).all()
    assert {s.status for s in slots} == {"open"}

    a = _annotator(db, "a@x.com")
    leased = next_task(db, a.id, proj.id)
    assert db.get(Unit, leased.unit_id).status == "in_progress"
    # The other, untouched unit is still pending.
    all_units = db.scalars(select(Unit).where(Unit.project_id == proj.id))
    others = [u for u in all_units if u.id != leased.unit_id]
    assert all(u.status == "pending" for u in others)


def test_next_resumes_an_existing_lease_instead_of_stranding_it(db) -> None:
    """One open task at a time: re-calling ``next_task`` without submitting hands
    back the slot already held (a reload picks up where you left off) rather than
    leasing a second and stranding the first (§ assignment resume)."""
    proj = _project(db, "resume", k=1)
    _ingest_sentiment(db, proj, n_regular=2)
    a = _annotator(db, "a@x.com")

    first = next_task(db, a.id, proj.id)
    assert first is not None
    again = next_task(db, a.id, proj.id)
    assert again is not None and again.id == first.id  # resumed, not a new lease
    assert db.get(Unit, first.unit_id).status == "in_progress"


def test_next_excludes_same_unit_for_annotator(db) -> None:
    proj = _project(db, "excl", k=2)
    _ingest_sentiment(db, proj, n_regular=2)
    a = _annotator(db, "a@x.com")

    s1 = next_task(db, a.id, proj.id)
    assert s1 is not None
    # Resume returns the held slot until it is submitted; then a *different* unit.
    submit_label(db, s1.id, a.id, raw={"sentiment": "positive"})
    s2 = next_task(db, a.id, proj.id)
    assert s2 is not None
    u1 = db.get(Slot, s1.id).unit_id
    u2 = db.get(Slot, s2.id).unit_id
    assert u1 != u2  # never the same unit twice (§2.7)
    # After both units are labeled by this annotator, no eligible slot remains.
    submit_label(db, s2.id, a.id, raw={"sentiment": "positive"})
    assert next_task(db, a.id, proj.id) is None


def test_two_annotators_share_a_units_slots(db) -> None:
    proj = _project(db, "share", k=2)
    _ingest_sentiment(db, proj, n_regular=1)
    a = _annotator(db, "a@x.com")
    b = _annotator(db, "b@x.com")

    sa = next_task(db, a.id, proj.id)
    sb = next_task(db, b.id, proj.id)
    assert sa is not None and sb is not None
    assert sa.id != sb.id  # different slots
    assert sa.unit_id == sb.unit_id  # same unit, both allowed
    # a re-calling resumes its own held slot (not b's, not a new one).
    assert next_task(db, a.id, proj.id).id == sa.id
    # Once a submits, it is excluded from that unit and there is no other → None.
    submit_label(db, sa.id, a.id, raw={"sentiment": "positive"})
    assert next_task(db, a.id, proj.id) is None


def test_submit_fills_slot_and_labels_unit(db) -> None:
    proj = _project(db, "submit", k=1)
    _ingest_sentiment(db, proj, n_regular=1)
    a = _annotator(db, "a@x.com")

    slot = next_task(db, a.id, proj.id)
    label = submit_label(db, slot.id, a.id, raw={"sentiment": "positive"})

    assert label.value == {"sentiment": "positive"}  # value defaults to raw
    assert db.get(Slot, slot.id).status == "filled"
    assert db.get(Unit, slot.unit_id).status == "labeled"


def test_submit_requires_held_lease(db) -> None:
    proj = _project(db, "held", k=1)
    _ingest_sentiment(db, proj, n_regular=1)
    a = _annotator(db, "a@x.com")
    b = _annotator(db, "b@x.com")
    slot = next_task(db, a.id, proj.id)

    # b did not lease this slot.
    with pytest.raises(AssignmentError):
        submit_label(db, slot.id, b.id, raw={"sentiment": "neutral"})


# --- skip / sweeper: reopen with variant retained ---------------------------


def test_skip_reopens_slot_variant_retained(db) -> None:
    proj = _project(db, "skip", k=4, variant=True)
    _ingest_sentiment_variant(db, proj)
    a = _annotator(db, "a@x.com")

    slot = next_task(db, a.id, proj.id)
    variant_before = slot.variant
    assert variant_before is not None

    skip_task(db, slot.id, a.id)
    reopened = db.get(Slot, slot.id)
    assert reopened.status == "open"
    assert reopened.leased_by is None
    assert reopened.variant == variant_before  # §2.7 variant retained


def test_sweeper_reclaims_expired_lease(db) -> None:
    proj = _project(db, "sweep", k=4, variant=True, lease_minutes=30)
    _ingest_sentiment_variant(db, proj)
    a = _annotator(db, "a@x.com")

    slot = next_task(db, a.id, proj.id, sweep=False)
    variant_before = slot.variant
    # Force the lease into the past, then sweep.
    slot.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.flush()

    reclaimed = sweep_expired_leases(db)
    assert reclaimed == 1
    swept = db.get(Slot, slot.id)
    assert swept.status == "open"
    assert swept.leased_by is None
    assert swept.variant == variant_before


# --- gold injection ratio ---------------------------------------------------


def test_gold_injection_hits_target_ratio(db) -> None:
    ratio = 0.2
    proj = _project(db, "gold", k=1, gold_ratio=ratio)
    # Plenty of both pools so we never run dry over 50 tasks.
    _ingest_sentiment(db, proj, n_regular=60, n_gold=30)
    a = _annotator(db, "a@x.com")

    n = 50
    gold_served = 0
    for _ in range(n):
        slot = next_task(db, a.id, proj.id)
        assert slot is not None
        unit = db.get(Unit, slot.unit_id)
        if unit.is_gold:
            gold_served += 1
        submit_label(db, slot.id, a.id, raw={"sentiment": "positive"})

    # Deterministic deficit rule → exactly floor(n * ratio) golds.
    assert gold_served == int(n * ratio)


# --- priority ---------------------------------------------------------------


def test_high_priority_drains_first(db) -> None:
    proj = _project(db, "prio", k=1)
    # Low-priority batch first, then high-priority batch.
    _ingest_sentiment(db, proj, n_regular=3, priority=0)
    high = _ingest_sentiment(db, proj, n_regular=3, priority=10)
    high_unit_ids = {r.unit_id for r in high.rows if r.ok}
    a = _annotator(db, "a@x.com")

    first_three = []
    for _ in range(3):
        slot = next_task(db, a.id, proj.id)
        first_three.append(slot.unit_id)
        submit_label(db, slot.id, a.id, raw={"sentiment": "neutral"})

    assert set(first_three) == high_unit_ids  # priority DESC wins


# --- void / requeue ---------------------------------------------------------


def test_void_unit_reopens_and_invalidates(db) -> None:
    proj = _project(db, "void", k=2)
    res = _ingest_sentiment(db, proj, n_regular=1)
    unit_id = next(r.unit_id for r in res.rows if r.ok)
    a = _annotator(db, "a@x.com")
    b = _annotator(db, "b@x.com")

    for ann in (a, b):
        slot = next_task(db, ann.id, proj.id)
        submit_label(db, slot.id, ann.id, raw={"sentiment": "positive"})
    assert db.get(Unit, unit_id).status == "labeled"

    voided = void_unit(db, unit_id)
    assert voided == 2
    assert db.get(Unit, unit_id).status == "pending"
    slots = db.scalars(select(Slot).where(Slot.unit_id == unit_id)).all()
    assert all(s.status == "open" for s in slots)
    valid = db.scalars(
        select(Label).where(Label.unit_id == unit_id, Label.is_valid.is_(True))
    ).all()
    assert valid == []


# --- variant ingest helper (declared late to keep the file readable) --------


def _ingest_sentiment_variant(db, project):
    """Side-by-side units (variant template) — one unit, K balanced slots."""
    line = '{"payload": {"prompt": "p", "response_a": "a", "response_b": "b"}}'
    return ingest_units(db, project, parse_jsonl(line))
