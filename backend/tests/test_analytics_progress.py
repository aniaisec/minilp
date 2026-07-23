"""Progress endpoint reconciles exactly with DB state (M5 acceptance, §11).

The acceptance criterion is "progress numbers reconcile exactly with DB state
under a seeded scenario (counts, consensus rates, ETA formula)". Rather than hard-
code expected numbers (brittle against assignment order), each test recomputes the
figure straight from the tables and asserts the progress payload matches — so the
endpoint and the database can never silently drift.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.models import Annotator, Label, Slot, Template, Unit, User
from app.services.analytics.progress import project_progress
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


def _project(db, name, *, template="image-classification", **kwargs):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == template))
    return create_project(db, name=name, template_id=tmpl.id, **kwargs)


def _ingest(db, project, rows, **kw):
    import json

    lines = "\n".join(json.dumps(r) for r in rows)
    return ingest_units(db, project, parse_jsonl(lines), **kw)


def _label_n_slots(db, annotators, project, n, raw):
    """Lease and submit up to n slots across the given annotators (round-robin)."""
    done = 0
    i = 0
    while done < n:
        ann = annotators[i % len(annotators)]
        slot = next_task(db, ann.id, project.id)
        if slot is None:
            i += 1
            if i > len(annotators) * (n + 2):
                break
            continue
        submit_label(db, slot.id, ann.id, raw=raw)
        done += 1
        i += 1
    return done


def _db_funnel(db, project_id):
    rows = db.execute(
        select(Unit.status, func.count()).where(Unit.project_id == project_id).group_by(Unit.status)
    ).all()
    return {s: c for s, c in rows}


def _db_slots(db, project_id):
    rows = db.execute(
        select(Slot.status, func.count())
        .join(Unit, Slot.unit_id == Unit.id)
        .where(Unit.project_id == project_id)
        .group_by(Slot.status)
    ).all()
    return {s: c for s, c in rows}


def test_funnel_and_slots_reconcile_with_db(db):
    project = _project(db, "prog", labels_per_unit=2, gold_ratio=0.0)
    a1, a2 = _annotator(db, "a1@x"), _annotator(db, "a2@x")
    _ingest(db, project, [{"payload": {"image_url": f"http://x/{i}.png"}} for i in range(4)])
    # Label 5 of the 8 slots (some units fully, some partially, one untouched).
    _label_n_slots(db, [a1, a2], project, 5, {"category": "cat"})

    prog = project_progress(db, project.id)

    db_funnel = _db_funnel(db, project.id)
    for status in ("pending", "in_progress", "labeled", "finalized"):
        assert prog["funnel"][status] == db_funnel.get(status, 0)
    assert prog["funnel"]["total"] == db.scalar(
        select(func.count()).select_from(Unit).where(Unit.project_id == project.id)
    )
    assert prog["slots"] == {
        "open": _db_slots(db, project.id).get("open", 0),
        "leased": _db_slots(db, project.id).get("leased", 0),
        "filled": _db_slots(db, project.id).get("filled", 0),
        "voided": _db_slots(db, project.id).get("voided", 0),
    }
    # Exactly 5 valid labels landed.
    assert prog["labels_total"] == 5
    assert prog["labels_total"] == db.scalar(
        select(func.count())
        .select_from(Label)
        .join(Unit, Label.unit_id == Unit.id)
        .where(Unit.project_id == project.id, Label.is_valid.is_(True))
    )


def test_remaining_slots_and_eta_formula(db):
    project = _project(db, "eta", labels_per_unit=2, gold_ratio=0.0)
    a1, a2 = _annotator(db, "e1@x"), _annotator(db, "e2@x")
    _ingest(db, project, [{"payload": {"image_url": f"http://x/{i}.png"}} for i in range(3)])
    _label_n_slots(db, [a1, a2], project, 4, {"category": "dog"})  # 4 of 6 slots filled

    now = datetime.now(UTC)
    prog = project_progress(db, project.id, now=now, window_hours=24.0)
    slots = prog["slots"]
    remaining = slots["open"] + slots["leased"]
    tp = prog["throughput"]
    assert tp["remaining_slots"] == remaining
    # 4 labels within the last 24h → rate 4/24; ETA = remaining / rate.
    assert tp["labels_in_window"] == 4
    assert tp["labels_per_hour"] == round(4 / 24.0, 4)
    if remaining:
        assert tp["eta_hours"] == round(remaining / (4 / 24.0), 4)


def test_per_variant_fill_is_balanced_for_side_by_side(db):
    project = _project(
        db, "bal", template="side-by-side-preference", labels_per_unit=2, gold_ratio=0.0
    )
    a1, a2 = _annotator(db, "v1@x"), _annotator(db, "v2@x")
    _ingest(
        db,
        project,
        [{"payload": {"prompt": f"p{i}", "response_a": "a", "response_b": "b"}} for i in range(3)],
    )
    _label_n_slots(db, [a1, a2], project, 4, {"choice": "Left"})

    prog = project_progress(db, project.id)
    variants = prog["variants"]
    assert variants["dimension"] == "panel_order"
    # K/n per value at creation → equal totals per variant value → balanced.
    assert variants["balanced"] is True
    totals = {v["value"]: v["total"] for v in variants["values"]}
    assert set(totals) == {"AB", "BA"}
    assert len(set(totals.values())) == 1  # exactly K/n each
    # Filled counts across variants sum to the filled-slot total.
    filled = sum(v["filled"] for v in variants["values"])
    assert filled == prog["slots"]["filled"]


def test_consensus_rate_counts_only_complete_units(db):
    project = _project(db, "cons", labels_per_unit=2, gold_ratio=0.0)
    a1, a2 = _annotator(db, "c1@x"), _annotator(db, "c2@x")
    _ingest(db, project, [{"payload": {"image_url": f"http://x/{i}.png"}} for i in range(2)])
    # Fully label BOTH units (4 slots) so both are complete and agree on "cat".
    _label_n_slots(db, [a1, a2], project, 4, {"category": "cat"})

    prog = project_progress(db, project.id)
    cons = prog["consensus"]
    labeled = db.scalar(
        select(func.count())
        .select_from(Unit)
        .where(Unit.project_id == project.id, Unit.status.in_(("labeled", "finalized")))
    )
    assert cons["complete_units"] == labeled
    # Everyone said "cat" → category key agrees on every complete unit.
    assert cons["keys"]["category"]["rate"] == 1.0
    assert cons["keys"]["category"]["complete"] == labeled


def test_progress_unknown_project_raises(db):
    import pytest

    with pytest.raises(ValueError):
        project_progress(db, 999999)
