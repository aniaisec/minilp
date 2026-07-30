"""M8 API surface through FastAPI (§5, §7.2): the review queue and the pipeline.

Role gating is asserted per endpoint rather than assumed. §5 puts the review
queue under ``reviewer`` — deciding an escalated unit *is* the reviewer role —
while editing the routing policy and re-running it over a whole project stay
``admin``, because both change what happens to every future unit.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import Annotator, User
from app.services.auth.roles import hash_api_key
from app.services.templates.seed import seed_templates
from app.services.webhooks import SendResult, set_default_sender

TRUNCATE = (
    "TRUNCATE templates, projects, batches, units, slots, labels, final_labels, "
    "users, annotators, judge_configs, judge_runs, judge_cache, reputation_events, "
    "webhooks, webhook_deliveries RESTART IDENTITY CASCADE"
)


# Two raters is the minimum that can disagree, which is the whole subject here.
RATERS = ("rater0@x.com", "rater1@x.com")


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
    for email, role, key in (
        ("admin@x.com", "admin", "admin-key"),
        ("rev@x.com", "reviewer", "rev-key"),
        ("ann@x.com", "annotator", "ann-key"),
    ):
        seeder.add(User(email=email, role=role, api_key_hash=hash_api_key(key)))
    rater_ids = []
    for email in RATERS:
        user = User(email=email, role="annotator", api_key_hash=hash_api_key(f"{email}-key"))
        seeder.add(user)
        seeder.flush()
        rater = Annotator(kind="human", user_id=user.id, display_name=email)
        seeder.add(rater)
        seeder.flush()
        rater_ids.append(rater.id)
    seeder.commit()
    seeder.close()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer admin-key"})
    c.rater_ids = rater_ids
    yield c
    app.dependency_overrides.clear()

    cleanup = Session(bind=engine)
    cleanup.execute(text(TRUNCATE))
    cleanup.commit()
    cleanup.close()


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, url, body, headers):
        self.calls.append((url, body, headers))
        return SendResult(True, status_code=200)

    def events(self):
        return [json.loads(body)["event"] for _, body, _ in self.calls]


@pytest.fixture()
def recorder():
    rec = _Recorder()
    set_default_sender(rec)
    try:
        yield rec
    finally:
        set_default_sender(None)


def _as(key):
    return {"Authorization": f"Bearer {key}"}


def _project(client, **kwargs):
    tid = next(
        t["id"] for t in client.get("/templates").json() if t["name"] == "image-classification"
    )
    body = {
        "name": "reviewed",
        "template_id": tid,
        "labels_per_unit": 2,
        "max_labels_per_unit": 2,
        "gold_ratio": 0.0,
        "agreement": {"category": {"match": "exact", "min_consensus": 0.9}},
    }
    body.update(kwargs)
    resp = client.post("/projects", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _units(client, project_id, n=2):
    rows = "\n".join(json.dumps({"payload": {"image_url": f"http://x/{i}.png"}}) for i in range(n))
    return client.post(
        f"/projects/{project_id}/units:bulk", json={"jsonl": rows, "format": "jsonl"}
    ).json()


def _label_unit(client, project_id, answers):
    """Have one rater per answer label the same unit, returning its unit id.

    Goes through ``/tasks/next`` + ``/tasks/{slot}/submit`` rather than inserting
    labels: the point of an API-level test is that escalation happens on the
    ordinary annotation path, with nobody calling routing by hand.
    """
    unit_ids = set()
    for annotator, answer in zip(client.rater_ids, answers, strict=True):
        task = client.get(f"/tasks/next?annotator={annotator}&project={project_id}")
        assert task.status_code == 200, task.text
        task = task.json()
        unit_ids.add(task["unit_id"])
        resp = client.post(
            f"/tasks/{task['slot_id']}/submit?annotator={annotator}",
            json={"raw": {"category": answer}},
        )
        assert resp.status_code == 201, resp.text
    assert len(unit_ids) == 1, "both raters must have been served the same unit"
    return unit_ids.pop()


# --- the queue ---------------------------------------------------------------


def test_a_disagreement_appears_in_the_queue_and_an_override_finalizes_it(client):
    project = _project(client)
    _units(client, project["id"], 1)
    unit_id = _label_unit(client, project["id"], ["cat", "dog"])

    queue = client.get(f"/review/queue?project={project['id']}", headers=_as("rev-key"))
    assert queue.status_code == 200
    body = queue.json()
    assert body["depth"] == 1
    item = body["items"][0]
    assert item["unit_id"] == unit_id
    assert item["proposal"]["votes"], "a reviewer must see the votes, not just the proposal"
    assert {v["value"]["category"] for v in item["proposal"]["votes"]} == {"cat", "dog"}

    detail = client.get(f"/review/{unit_id}", headers=_as("rev-key")).json()
    assert detail["template"]["schema"]["inputs"]
    assert detail["final_label"] is None

    decided = client.post(
        f"/review/{unit_id}:decide",
        json={"decision": "override", "value": {"category": "bird"}, "comment": "misread"},
        headers=_as("rev-key"),
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["method"] == "human_override"
    assert decided.json()["queue_depth"] == 0

    after = client.get(f"/review/{unit_id}", headers=_as("rev-key")).json()
    assert after["final_label"]["value"] == {"category": "bird"}
    assert after["final_label"]["method"] == "human_override"
    assert (
        client.get(f"/review/queue?project={project['id']}", headers=_as("rev-key")).json()["depth"]
        == 0
    )


def test_approving_takes_the_proposal(client):
    project = _project(client)
    _units(client, project["id"], 1)
    unit_id = _label_unit(client, project["id"], ["cat", "dog"])

    decided = client.post(
        f"/review/{unit_id}:decide", json={"decision": "approve"}, headers=_as("rev-key")
    ).json()
    assert decided["method"] == "human_approved"
    assert decided["value"]["category"] in ("cat", "dog")


def test_an_override_without_a_value_is_a_422(client):
    project = _project(client)
    _units(client, project["id"], 1)
    unit_id = _label_unit(client, project["id"], ["cat", "dog"])
    resp = client.post(
        f"/review/{unit_id}:decide", json={"decision": "override"}, headers=_as("rev-key")
    )
    assert resp.status_code == 422


def test_an_unknown_decision_is_rejected_by_the_schema(client):
    project = _project(client)
    _units(client, project["id"], 1)
    unit_id = _label_unit(client, project["id"], ["cat", "dog"])
    resp = client.post(
        f"/review/{unit_id}:decide", json={"decision": "shrug"}, headers=_as("rev-key")
    )
    assert resp.status_code == 422


def test_reviewing_an_unknown_unit_is_a_404(client):
    assert client.get("/review/999999", headers=_as("rev-key")).status_code == 404


# --- role gating (§5) --------------------------------------------------------


def test_the_queue_is_reviewer_gated(client):
    project = _project(client)
    _units(client, project["id"], 1)
    unit_id = _label_unit(client, project["id"], ["cat", "dog"])

    for path in (f"/review/queue?project={project['id']}", f"/review/{unit_id}", "/review/depth"):
        assert client.get(path, headers=_as("ann-key")).status_code == 403
        assert client.get(path, headers=_as("rev-key")).status_code == 200

    assert (
        client.post(
            f"/review/{unit_id}:decide", json={"decision": "approve"}, headers=_as("ann-key")
        ).status_code
        == 403
    )


def test_editing_the_pipeline_is_admin_only_but_reading_is_reviewer(client):
    project = _project(client)
    pid = project["id"]

    assert client.get(f"/projects/{pid}/pipeline", headers=_as("ann-key")).status_code == 403
    assert client.get(f"/projects/{pid}/pipeline", headers=_as("rev-key")).status_code == 200

    body = {"pipeline": [{"stage": "ensemble"}, {"stage": "human_review"}]}
    put = f"/projects/{pid}/pipeline"
    assert client.put(put, json=body, headers=_as("rev-key")).status_code == 403
    assert client.put(put, json=body, headers=_as("admin-key")).status_code == 200

    route = f"/projects/{pid}/route"
    assert client.post(route, json={}, headers=_as("rev-key")).status_code == 403
    assert client.post(route, json={}, headers=_as("admin-key")).status_code == 200


# --- the pipeline document ---------------------------------------------------


def test_the_pipeline_endpoint_reports_the_default_and_what_can_go_in_it(client):
    project = _project(client)
    body = client.get(f"/projects/{project['id']}/pipeline").json()
    assert body["is_default"] is True
    assert [s["stage"] for s in body["pipeline"]] == ["ensemble", "auto_finalize", "human_review"]
    # The editor needs to know the vocabulary, not guess it.
    assert {"ensemble", "auto_finalize", "human_review"} <= set(body["stages"])
    assert {"consensus", "entropy", "votes"} <= set(body["variables"])


def test_an_unparseable_condition_is_a_422_not_a_rule_that_never_fires(client):
    project = _project(client)
    resp = client.put(
        f"/projects/{project['id']}/pipeline",
        json={"pipeline": [{"stage": "auto_finalize", "if": "consensuss >= 0.9"}]},
        headers=_as("admin-key"),
    )
    assert resp.status_code == 422
    assert "unknown variable" in resp.json()["detail"]


def test_putting_null_resets_to_the_shipped_default(client):
    project = _project(client)
    pid = project["id"]
    client.put(f"/projects/{pid}/pipeline", json={"pipeline": [{"stage": "human_review"}]})
    assert client.get(f"/projects/{pid}/pipeline").json()["is_default"] is False
    client.put(f"/projects/{pid}/pipeline", json={"pipeline": None})
    assert client.get(f"/projects/{pid}/pipeline").json()["is_default"] is True


def test_routing_can_be_re_run_over_a_project_after_a_policy_change(client):
    """A pipeline is a setting; changing it must be applicable to the units
    already sitting in the project, not only to ones labeled afterwards."""
    project = _project(
        client, agreement={"category": {"match": "exact", "min_consensus": 0.4}}, labels_per_unit=2
    )
    pid = project["id"]
    _units(client, pid, 1)
    unit_id = _label_unit(client, pid, ["cat", "dog"])

    # Under a lenient agreement policy and the default pipeline this unit is not
    # decisive enough to auto-finalize, so it is already in review.
    assert client.get("/review/depth", headers=_as("rev-key")).json()["depth"] == 1

    # Switch to a pipeline that finalizes anything, then re-run.
    client.put(
        f"/projects/{pid}/pipeline",
        json={
            "pipeline": [
                {"stage": "ensemble"},
                {"stage": "auto_finalize", "if": "votes >= 1"},
            ]
        },
    )
    report = client.post(f"/projects/{pid}/route", json={"include_finalized": True}).json()
    assert report["units_considered"] >= 1

    detail = client.get(f"/review/{unit_id}", headers=_as("rev-key")).json()
    assert detail["final_label"]["method"] == "auto_consensus"
    assert client.get("/review/depth", headers=_as("rev-key")).json()["depth"] == 0


def test_a_human_decision_survives_a_re_route(client):
    project = _project(client)
    pid = project["id"]
    _units(client, pid, 1)
    unit_id = _label_unit(client, pid, ["cat", "dog"])
    client.post(
        f"/review/{unit_id}:decide",
        json={"decision": "override", "value": {"category": "bird"}},
        headers=_as("rev-key"),
    )

    report = client.post(f"/projects/{pid}/route", json={"include_finalized": True}).json()
    assert report["skipped"] >= 1
    detail = client.get(f"/review/{unit_id}", headers=_as("rev-key")).json()
    assert detail["final_label"]["value"] == {"category": "bird"}


# --- webhooks through the API (§7.3) -----------------------------------------


def test_the_backlog_webhook_fires_through_the_ordinary_submit_path(client, recorder):
    project = _project(client, config={"review": {"backlog_threshold": 2}})
    pid = project["id"]
    client.post(
        "/webhooks",
        json={
            "event": "review.queue_backlog",
            "target_url": "https://example.test/backlog",
            "project_id": pid,
        },
    )
    _units(client, pid, 3)
    for _ in range(3):
        _label_unit(client, pid, ["cat", "dog"])

    assert recorder.events() == ["review.queue_backlog"]
    deliveries = client.get(f"/webhooks/deliveries?project={pid}").json()
    assert [d["event"] for d in deliveries] == ["review.queue_backlog"]
    assert deliveries[0]["status"] == "delivered"
    assert deliveries[0]["payload"]["metric"] == {"queue_depth": 2, "threshold": 2}


def test_project_completed_fires_when_the_last_unit_is_decided(client, recorder):
    project = _project(client)
    pid = project["id"]
    client.post(
        "/webhooks",
        json={
            "event": "project.completed",
            "target_url": "https://example.test/done",
            "project_id": pid,
        },
    )
    _units(client, pid, 1)
    unit_id = _label_unit(client, pid, ["cat", "dog"])
    assert recorder.events() == []

    client.post(
        f"/review/{unit_id}:decide",
        json={"decision": "override", "value": {"category": "bird"}},
        headers=_as("rev-key"),
    )
    assert recorder.events() == ["project.completed"]
