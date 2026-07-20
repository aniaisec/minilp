"""Quality endpoints through FastAPI (§5): annotator reports, resume, agreement.

Also pins the two blinding rules that matter for data integrity:
golds must stay indistinguishable in the submit response (§6.1), and an annotator
must not learn their peers' votes from it (§6.3).
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import Annotator, Template, User
from app.services.auth.roles import hash_api_key
from app.services.templates.seed import seed_templates

ADMIN_KEY = "admin-key"
ANNOTATOR_KEY = "worker-key"
OTHER_KEY = "other-key"


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

    seeder = Session(bind=engine, expire_on_commit=False)
    seed_templates(seeder)
    seeder.add(User(email="admin@x.com", role="admin", api_key_hash=hash_api_key(ADMIN_KEY)))
    worker = User(email="worker@x.com", role="annotator", api_key_hash=hash_api_key(ANNOTATOR_KEY))
    other = User(email="other@x.com", role="annotator", api_key_hash=hash_api_key(OTHER_KEY))
    seeder.add_all([worker, other])
    seeder.flush()
    seeder.add_all(
        [
            Annotator(kind="human", user_id=worker.id, display_name="worker"),
            Annotator(kind="human", user_id=other.id, display_name="other"),
        ]
    )
    seeder.commit()
    seeder.close()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {ADMIN_KEY}"})
    yield c
    app.dependency_overrides.clear()

    cleanup = Session(bind=engine)
    cleanup.execute(
        text(
            "TRUNCATE templates, projects, batches, units, slots, labels, "
            "final_labels, users, annotators, judge_configs, reputation_events, "
            "webhooks RESTART IDENTITY CASCADE"
        )
    )
    cleanup.commit()
    cleanup.close()


def _annotator_ids(engine) -> tuple[int, int]:
    with Session(bind=engine) as s:
        ids = list(s.scalars(select(Annotator.id).order_by(Annotator.id)))
    return ids[0], ids[1]


def _template_id(engine, name: str) -> int:
    with Session(bind=engine) as s:
        return s.scalar(select(Template.id).where(Template.name == name))


def _make_project(client, engine, **kwargs) -> int:
    body = {
        "name": kwargs.pop("name", "quality-proj"),
        "template_id": _template_id(engine, "image-classification"),
        "labels_per_unit": 1,
        "gold_ratio": 0.0,
        **kwargs,
    }
    resp = client.post("/projects", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _ingest(client, project_id, rows):
    resp = client.post(
        f"/projects/{project_id}/units:bulk",
        json={"jsonl": "\n".join(json.dumps(r) for r in rows)},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _unit(gold: str | None = None):
    row = {"payload": {"image_url": "http://x/1.png"}}
    if gold:
        row |= {"is_gold": True, "gold_expected": {"category": gold}}
    return row


# --- submit response blinding (§6.1, §6.3) ----------------------------------


def test_submit_response_never_reveals_gold_outcome(client, engine):
    project = _make_project(client, engine, gold_ratio=1.0)
    _ingest(client, project, [_unit(gold="cat")])
    worker, _ = _annotator_ids(engine)

    task = client.get(f"/tasks/next?annotator={worker}&project={project}").json()
    resp = client.post(
        f"/tasks/{task['slot_id']}/submit?annotator={worker}",
        json={"raw": {"category": "dog"}},
    )
    assert resp.status_code == 201
    quality = resp.json()["quality"]
    assert set(quality) == {"paused", "labels_voided", "reputation", "flags"}
    assert "gold" not in json.dumps(quality)
    assert "consensus" not in quality


def test_submit_returns_the_server_canonicalized_value(client, engine):
    project = _make_project(client, engine)
    _ingest(client, project, [_unit()])
    worker, _ = _annotator_ids(engine)

    task = client.get(f"/tasks/next?annotator={worker}&project={project}").json()
    resp = client.post(
        f"/tasks/{task['slot_id']}/submit?annotator={worker}",
        json={"raw": {"category": "other:capybara"}, "value": {"category": "lies"}},
    )
    assert resp.json()["value"] == {"category": "capybara"}


# --- annotator report (§5) --------------------------------------------------


def test_annotator_report_shape(client, engine):
    worker, _ = _annotator_ids(engine)
    resp = client.get(f"/annotators/{worker}/report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["annotator_id"] == worker
    assert body["status"] == "active"
    assert "reputation_score" in body
    assert "gold_accuracy" in body["live"]
    assert body["events"] == []


def test_annotator_may_read_their_own_report_but_not_anothers(client, engine):
    worker, other = _annotator_ids(engine)
    client.headers.update({"Authorization": f"Bearer {ANNOTATOR_KEY}"})

    assert client.get(f"/annotators/{worker}/report").status_code == 200
    assert client.get(f"/annotators/{other}/report").status_code == 403


def test_report_shows_the_pause_reason_after_a_gold_collapse(client, engine):
    project = _make_project(
        client,
        engine,
        gold_ratio=1.0,
        config={"quality": {"gold_threshold": 0.9, "gold_min_samples": 2}},
    )
    _ingest(client, project, [_unit(gold="cat") for _ in range(3)])
    worker, _ = _annotator_ids(engine)

    for _ in range(2):
        task = client.get(f"/tasks/next?annotator={worker}&project={project}").json()
        client.post(
            f"/tasks/{task['slot_id']}/submit?annotator={worker}",
            json={"raw": {"category": "dog"}},
        )

    report = client.get(f"/annotators/{worker}/report").json()
    assert report["status"] == "paused"
    assert "gold accuracy" in report["pause_reason"]
    assert any(e["kind"] == "gold_fail" for e in report["events"])

    # A paused annotator gets 403 with the reason, not a silent empty queue.
    blocked = client.get(f"/tasks/next?annotator={worker}&project={project}")
    assert blocked.status_code == 403
    assert "gold accuracy" in blocked.json()["detail"]

    # Admin resume puts them back to work.
    assert client.post(f"/annotators/{worker}:resume").status_code == 200
    assert client.get(f"/tasks/next?annotator={worker}&project={project}").status_code == 200


def test_resume_is_admin_only(client, engine):
    worker, _ = _annotator_ids(engine)
    client.headers.update({"Authorization": f"Bearer {ANNOTATOR_KEY}"})
    assert client.post(f"/annotators/{worker}:resume").status_code == 403


# --- agreement analytics (§6.3) ---------------------------------------------


def test_agreement_endpoint_reports_per_key_kappa(client, engine):
    project = _make_project(client, engine, name="agree", labels_per_unit=2)
    _ingest(client, project, [_unit(), _unit()])
    worker, other = _annotator_ids(engine)

    for annotator in (worker, other):
        for _ in range(2):
            task = client.get(f"/tasks/next?annotator={annotator}&project={project}").json()
            client.post(
                f"/tasks/{task['slot_id']}/submit?annotator={annotator}",
                json={"raw": {"category": "cat"}},
            )

    body = client.get(f"/projects/{project}/analytics/agreement").json()
    assert body["group"] == "all"
    assert body["keys"]["category"]["observed_agreement"] == 1.0
    assert body["keys"]["category"]["mean_entropy"] == 0.0


def test_agreement_rejects_an_unknown_group(client, engine):
    project = _make_project(client, engine, name="badgroup")
    assert client.get(f"/projects/{project}/analytics/agreement?group=vibes").status_code == 422


def test_agreement_requires_reviewer_or_above(client, engine):
    project = _make_project(client, engine, name="gated-analytics")
    client.headers.update({"Authorization": f"Bearer {ANNOTATOR_KEY}"})
    assert client.get(f"/projects/{project}/analytics/agreement").status_code == 403


def test_consensus_endpoint_lists_escalated_units(client, engine):
    project = _make_project(
        client,
        engine,
        name="escalations",
        labels_per_unit=2,
        max_labels_per_unit=2,
        agreement={"category": {"match": "exact", "min_consensus": 0.9}},
    )
    _ingest(client, project, [_unit()])
    worker, other = _annotator_ids(engine)

    for annotator, answer in ((worker, "cat"), (other, "dog")):
        task = client.get(f"/tasks/next?annotator={annotator}&project={project}").json()
        client.post(
            f"/tasks/{task['slot_id']}/submit?annotator={annotator}",
            json={"raw": {"category": answer}},
        )

    body = client.get(f"/projects/{project}/consensus?escalated=true").json()
    assert body["count"] == 1
    assert body["units"][0]["consensus"]["action"] == "escalated"
    assert client.get(f"/projects/{project}/consensus?escalated=false").json()["count"] == 0
