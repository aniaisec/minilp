"""M9 API surface through FastAPI (§5, §8): batch selection, checkpoint
re-enrollment, the iteration eval curve.

Role gating mirrors §5's existing judge/cost split: the two read endpoints are
``reviewer`` (deciding what the next round prioritizes, like costs and
progress); registering a checkpoint is ``admin`` (it enrolls a rater and may
spend money, like every other judge-config write, §7.1).
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import User
from app.services.auth.roles import hash_api_key
from app.services.templates.seed import seed_templates

TRUNCATE = (
    "TRUNCATE templates, projects, batches, units, slots, labels, final_labels, "
    "users, annotators, judge_configs, judge_runs, judge_cache, reputation_events, "
    "webhooks, webhook_deliveries RESTART IDENTITY CASCADE"
)


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
    seeder.commit()
    seeder.close()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer admin-key"})
    yield c
    app.dependency_overrides.clear()

    cleanup = Session(bind=engine)
    cleanup.execute(text(TRUNCATE))
    cleanup.commit()
    cleanup.close()


def _as(client, key):
    return {"Authorization": f"Bearer {key}"}


def _project(client, *, template="image-classification", **kwargs):
    tid = next(t["id"] for t in client.get("/templates").json() if t["name"] == template)
    body = {"name": "al-api", "template_id": tid, "labels_per_unit": 1, "gold_ratio": 0.0}
    body.update(kwargs)
    return client.post("/projects", json=body).json()


def _units(client, project_id, n=3):
    rows = "\n".join(json.dumps({"payload": {"image_url": f"http://x/{i}.png"}}) for i in range(n))
    return client.post(
        f"/projects/{project_id}/units:bulk", json={"jsonl": rows, "format": "jsonl"}
    ).json()


def _checkpoint(client, project_id, *, headers=None, **kwargs):
    body = {"name": "api-student", "provider": "mock", "model_id": "ckpt-1"}
    body.update(kwargs)
    url = f"/projects/{project_id}/active-learning/checkpoints:register"
    if headers is not None:
        return client.post(url, json=body, headers=headers)
    return client.post(url, json=body)


# --- batch ---------------------------------------------------------------------


def test_batch_endpoint_returns_the_open_pool(client):
    project = _project(client)
    _units(client, project["id"], 3)

    resp = client.get(f"/projects/{project['id']}/active-learning/batch")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pool_size"] == 3
    assert len(body["units"]) == 3
    assert all(u["score"] == 0.5 for u in body["units"]), "no votes yet: neutral score"


def test_batch_endpoint_respects_limit(client):
    project = _project(client)
    _units(client, project["id"], 5)
    resp = client.get(f"/projects/{project['id']}/active-learning/batch", params={"limit": 2})
    assert len(resp.json()["units"]) == 2


def test_batch_endpoint_on_unknown_project_is_404(client):
    assert client.get("/projects/999999/active-learning/batch").status_code == 404


def test_batch_endpoint_is_reviewer_gated_not_annotator(client):
    project = _project(client)
    assert (
        client.get(
            f"/projects/{project['id']}/active-learning/batch", headers=_as(client, "rev-key")
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/projects/{project['id']}/active-learning/batch", headers=_as(client, "ann-key")
        ).status_code
        == 403
    )


# --- checkpoints:register --------------------------------------------------------


def test_register_checkpoint_creates_and_attaches(client):
    project = _project(client)
    resp = _checkpoint(client, project["id"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["iteration"] == 1
    assert body["annotator_id"] is not None

    enrolled = client.get(f"/projects/{project['id']}/judges").json()["judges"]
    assert any(j["judge_config_id"] == body["judge_config_id"] for j in enrolled)


def test_register_checkpoint_bumps_the_iteration_on_a_second_call(client):
    project = _project(client)
    v1 = _checkpoint(client, project["id"], model_id="ckpt-1").json()
    v2 = _checkpoint(client, project["id"], model_id="ckpt-2").json()
    assert (v1["iteration"], v2["iteration"]) == (1, 2)
    assert v1["judge_config_id"] != v2["judge_config_id"]


def test_register_checkpoint_on_unknown_project_is_404(client):
    resp = _checkpoint(client, 999999)
    assert resp.status_code == 404


def test_register_checkpoint_is_admin_only(client):
    project = _project(client)
    for headers in (_as(client, "rev-key"), _as(client, "ann-key")):
        assert _checkpoint(client, project["id"], headers=headers).status_code == 403


# --- iterations ------------------------------------------------------------------


def test_iterations_endpoint_reports_the_eval_curve(client):
    project = _project(client)
    _units(client, project["id"], 2)
    ckpt = _checkpoint(client, project["id"]).json()
    client.post(
        f"/projects/{project['id']}/judges:run", json={"judge_config_id": ckpt["judge_config_id"]}
    )

    resp = client.get(
        f"/projects/{project['id']}/active-learning/iterations", params={"name": "api-student"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["iterations"]) == 1
    point = body["iterations"][0]
    assert point["iteration"] == 1
    assert point["label_count"] == 2
    assert "human_minutes" in body


def test_iterations_endpoint_requires_name(client):
    project = _project(client)
    resp = client.get(f"/projects/{project['id']}/active-learning/iterations")
    assert resp.status_code == 422


def test_iterations_endpoint_on_unknown_name_is_404(client):
    project = _project(client)
    resp = client.get(
        f"/projects/{project['id']}/active-learning/iterations", params={"name": "nope"}
    )
    assert resp.status_code == 404


def test_iterations_endpoint_is_reviewer_gated_not_annotator(client):
    project = _project(client)
    _checkpoint(client, project["id"])
    assert (
        client.get(
            f"/projects/{project['id']}/active-learning/iterations",
            params={"name": "api-student"},
            headers=_as(client, "rev-key"),
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/projects/{project['id']}/active-learning/iterations",
            params={"name": "api-student"},
            headers=_as(client, "ann-key"),
        ).status_code
        == 403
    )
