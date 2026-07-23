"""Annotator landing-page availability (§11, M5).

``available_work`` must count exactly what ``next_task`` would keep serving —
same annotator-unit exclusion — and order projects with the most remaining work
first. The API layer's auth is covered in ``test_analytics_api``-style fashion here
too: a human may list only their own work.
"""

import json

import pytest
from sqlalchemy import select

from app.models import Annotator, Template, User
from app.services.assignment import available_work, next_task, submit_label
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.quality.reputation import pause_annotator
from app.services.templates.seed import seed_templates


def _annotator(db, email):
    user = User(email=email, role="annotator")
    db.add(user)
    db.flush()
    ann = Annotator(kind="human", user_id=user.id, display_name=email)
    db.add(ann)
    db.flush()
    return ann


def _project(db, name, *, template="image-classification", **kw):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == template))
    return create_project(db, name=name, template_id=tmpl.id, **kw)


def _ingest(db, project, n):
    rows = [{"payload": {"image_url": f"http://x/{i}.png"}} for i in range(n)]
    return ingest_units(db, project, parse_jsonl("\n".join(json.dumps(r) for r in rows)))


def _by_id(work, pid):
    return next(w for w in work if w["project_id"] == pid)


def test_counts_eligible_open_slots_per_project(db):
    p1 = _project(db, "p1", labels_per_unit=2, gold_ratio=0.0)
    p2 = _project(db, "p2", labels_per_unit=1, gold_ratio=0.0)
    _ingest(db, p1, 3)  # 3 units * 2 slots = 6 open
    _ingest(db, p2, 2)  # 2 units * 1 slot = 2 open
    ann = _annotator(db, "a@x")

    work = available_work(db, ann.id)
    assert _by_id(work, p1.id)["available_labels"] == 6
    assert _by_id(work, p1.id)["open_units"] == 3
    assert _by_id(work, p2.id)["available_labels"] == 2
    # Most work first (p1 before p2).
    assert [w["project_id"] for w in work][:2] == [p1.id, p2.id]


def test_excludes_units_the_annotator_already_labeled(db):
    project = _project(db, "excl", labels_per_unit=2, gold_ratio=0.0)
    _ingest(db, project, 2)  # 4 open slots across 2 units
    ann = _annotator(db, "e@x")

    # Label one slot: that unit is now excluded for this annotator (can't label the
    # same unit's other variant), so available drops by the whole unit's remaining.
    slot = next_task(db, ann.id, project.id)
    submit_label(db, slot.id, ann.id, raw={"category": "cat"})

    work = available_work(db, ann.id)
    row = _by_id(work, project.id)
    # Only the *other* unit's 2 slots remain eligible for this annotator.
    assert row["available_labels"] == 2
    assert row["open_units"] == 1
    assert row["your_labels"] == 1


def test_finished_projects_sink_below_ones_needing_labels(db):
    todo = _project(db, "todo", labels_per_unit=1, gold_ratio=0.0)
    done = _project(db, "done", labels_per_unit=1, gold_ratio=0.0)
    _ingest(db, todo, 2)
    _ingest(db, done, 1)
    ann = _annotator(db, "s@x")
    # Finish the "done" project with a second annotator so it isn't merely
    # excluded-for-ann but genuinely has no open slots.
    other = _annotator(db, "o@x")
    slot = next_task(db, other.id, done.id)
    submit_label(db, slot.id, other.id, raw={"category": "cat"})

    work = available_work(db, ann.id)
    assert _by_id(work, done.id)["available_labels"] == 0
    # "todo" (needs labels) ranks ahead of "done" (finished).
    order = [w["project_id"] for w in work]
    assert order.index(todo.id) < order.index(done.id)


def test_paused_annotator_sees_work_but_marked_ineligible(db):
    project = _project(db, "paused", labels_per_unit=1, gold_ratio=0.0)
    _ingest(db, project, 2)
    ann = _annotator(db, "p@x")
    pause_annotator(db, ann.id, project.id, reason="manual test pause")

    row = _by_id(available_work(db, ann.id), project.id)
    assert row["eligible"] is False
    assert "pause" in (row["blocked_reason"] or "").lower()
    # The remaining work is still reported so the UI can explain the block.
    assert row["available_labels"] == 2


def test_unknown_annotator_raises(db):
    from app.services.assignment import AssignmentError

    with pytest.raises(AssignmentError):
        available_work(db, 999999)
