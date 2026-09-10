"""Task events (measurement instrumentation) — every slot transition the
assignment engine performs leaves a row, including the ones ``labels`` cannot
see: skips, exits, judge releases and expired leases.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import Annotator, TaskEvent, Template, User
from app.services.assignment import (
    AssignmentError,
    next_task,
    skip_task,
    submit_label,
    sweep_expired_leases,
)
from app.services.auth.roles import hash_api_key
from app.services.export import export_rows
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.templates.seed import seed_templates


def _annotator(db, email: str) -> Annotator:
    user = User(email=email, role="annotator")
    db.add(user)
    db.flush()
    ann = Annotator(kind="human", user_id=user.id, display_name=email)
    db.add(ann)
    db.flush()
    return ann


def _project(db, n_units: int = 2, **kwargs):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == "image-classification"))
    project = create_project(
        db, name="events", template_id=tmpl.id, labels_per_unit=1, gold_ratio=0.0, **kwargs
    )
    rows = [{"payload": {"image_url": f"http://x/{i}.png"}} for i in range(n_units)]
    ingest_units(db, project, parse_jsonl("\n".join(json.dumps(r) for r in rows)))
    return project


def _kinds(db, project_id: int) -> list[str]:
    return list(
        db.scalars(
            select(TaskEvent.kind)
            .where(TaskEvent.project_id == project_id)
            .order_by(TaskEvent.at, TaskEvent.id)
        )
    )


def test_lease_then_submit_logs_both_with_the_label(db) -> None:
    project = _project(db)
    ann = _annotator(db, "a@x")
    slot = next_task(db, ann.id, project.id)
    label = submit_label(db, slot.id, ann.id, raw={"category": "cat"})

    assert _kinds(db, project.id) == ["leased", "submitted"]
    submitted = db.scalar(select(TaskEvent).where(TaskEvent.kind == "submitted"))
    assert submitted.label_id == label.id
    assert (submitted.annotator_id, submitted.slot_id) == (ann.id, slot.id)


def test_a_reload_logs_resumed_not_a_second_lease(db) -> None:
    project = _project(db)
    ann = _annotator(db, "r@x")
    first = next_task(db, ann.id, project.id)
    again = next_task(db, ann.id, project.id)
    assert again.id == first.id
    assert _kinds(db, project.id) == ["leased", "resumed"]


@pytest.mark.parametrize(
    ("reason", "kind"), [("skip", "skipped"), ("exit", "exited"), ("release", "released")]
)
def test_each_release_reason_logs_its_own_kind(db, reason, kind) -> None:
    project = _project(db)
    ann = _annotator(db, f"{reason}@x")
    slot = next_task(db, ann.id, project.id)
    skip_task(db, slot.id, ann.id, reason=reason)
    assert _kinds(db, project.id) == ["leased", kind]
    assert slot.status == "open"  # the reason changes the log, not the slot


def test_an_unknown_reason_is_refused_before_anything_changes(db) -> None:
    project = _project(db)
    ann = _annotator(db, "bad@x")
    slot = next_task(db, ann.id, project.id)
    with pytest.raises(AssignmentError) as err:
        skip_task(db, slot.id, ann.id, reason="teleport")
    assert err.value.status == 422
    assert slot.status == "leased"
    assert _kinds(db, project.id) == ["leased"]


def test_an_expired_lease_is_logged_against_whoever_abandoned_it(db) -> None:
    project = _project(db, lease_minutes=5)
    ann = _annotator(db, "gone@x")
    t0 = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    slot = next_task(db, ann.id, project.id, now=t0)

    assert sweep_expired_leases(db, now=t0 + timedelta(minutes=6)) == 1
    expired = db.scalar(select(TaskEvent).where(TaskEvent.kind == "expired"))
    assert (expired.slot_id, expired.annotator_id) == (slot.id, ann.id)
    assert expired.at == t0 + timedelta(minutes=6)


def test_a_skipped_slot_comes_straight_back_to_the_skipper(db) -> None:
    """Characterizes current behaviour, which the study measures as
    ``reserved_after_skip``: skipping reopens the slot for everyone, including
    the annotator who skipped it, and nothing excludes it from their next pull."""
    project = _project(db, n_units=3)
    ann = _annotator(db, "again@x")
    slot = next_task(db, ann.id, project.id)
    skip_task(db, slot.id, ann.id)
    assert next_task(db, ann.id, project.id).id == slot.id


def test_events_export_rows(db) -> None:
    project = _project(db)
    ann = _annotator(db, "exp@x")
    slot = next_task(db, ann.id, project.id)
    skip_task(db, slot.id, ann.id, reason="exit")

    rows = list(export_rows(db, project.id, "events"))
    assert [r["kind"] for r in rows] == ["leased", "exited"]
    assert rows[0]["annotator_kind"] == "human"
    assert rows[0]["slot_id"] == slot.id and rows[0]["variant_value"] is None
    datetime.fromisoformat(rows[0]["at"])  # ISO, parseable by the report


# --- API: the reason travels over the wire -------------------------------------


@pytest.fixture()
def client(engine):
    def override_get_db():
        s = Session(bind=engine, expire_on_commit=False)
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

    cleanup = Session(bind=engine)
    cleanup.execute(
        text(
            "TRUNCATE templates, projects, batches, units, slots, labels, task_events, "
            "final_labels, users, annotators, reputation_events RESTART IDENTITY CASCADE"
        )
    )
    cleanup.commit()
    cleanup.close()


def test_skip_endpoint_takes_exit_and_refuses_release(engine, client) -> None:
    setup = Session(bind=engine, expire_on_commit=False)
    project = _project(setup)
    user = User(email="api@x", role="annotator", api_key_hash=hash_api_key("ann-key"))
    setup.add(user)
    setup.flush()
    ann = Annotator(kind="human", user_id=user.id, display_name="api")
    setup.add(ann)
    setup.commit()
    ids = (project.id, ann.id)
    setup.close()
    client.headers.update({"Authorization": "Bearer ann-key"})

    task = client.get(f"/tasks/next?annotator={ids[1]}&project={ids[0]}").json()
    refused = client.post(f"/tasks/{task['slot_id']}/skip?annotator={ids[1]}&reason=release")
    assert refused.status_code == 422
    left = client.post(f"/tasks/{task['slot_id']}/skip?annotator={ids[1]}&reason=exit")
    assert left.status_code == 200

    check = Session(bind=engine)
    assert _kinds(check, ids[0]) == ["leased", "exited"]
    check.close()
