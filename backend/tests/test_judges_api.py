"""M7 API surface through FastAPI (§5): judges, runs, costs, webhooks.

Role gating is asserted per endpoint, not assumed. §5 puts judges and webhooks
under ``admin`` because both are decisions to spend money or to open an outbound
channel; costs and run history are ``reviewer`` because deciding the next round's
K needs them.
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
    body = {"name": "judged", "template_id": tid, "labels_per_unit": 1, "gold_ratio": 0.0}
    body.update(kwargs)
    return client.post("/projects", json=body).json()


def _units(client, project_id, n=4):
    rows = "\n".join(json.dumps({"payload": {"image_url": f"http://x/{i}.png"}}) for i in range(n))
    return client.post(
        f"/projects/{project_id}/units:bulk", json={"jsonl": rows, "format": "jsonl"}
    ).json()


def _judge(client, **kwargs):
    body = {"name": "mock-judge", "provider": "mock", "model_id": "mock-1"}
    body.update(kwargs)
    return client.post("/judges", json=body).json()


# --- judge configs -----------------------------------------------------------


def test_create_list_and_fetch_a_judge_config(client):
    created = _judge(client, params={"temperature": 0.0}, budget={"project_usd": 1.0})
    assert created["prompt_version"] == 1
    assert created["provider"] == "mock"

    assert any(j["id"] == created["id"] for j in client.get("/judges").json())
    assert client.get(f"/judges/{created['id']}").json()["model_id"] == "mock-1"


def test_providers_endpoint_lists_the_registry(client):
    providers = client.get("/judges/providers").json()["providers"]
    assert {"mock", "anthropic", "openai", "openai_compatible"} <= set(providers)


def test_an_unknown_provider_is_a_422(client):
    resp = client.post("/judges", json={"name": "x", "provider": "vibes", "model_id": "m"})
    assert resp.status_code == 422
    assert "unknown provider" in resp.json()["detail"]


def test_an_unknown_budget_key_is_rejected_rather_than_ignored(client):
    """A typo'd cap that silently does nothing is the failure caps exist to stop."""
    resp = client.post(
        "/judges",
        json={"name": "x", "provider": "mock", "model_id": "m", "budget": {"dayly_usd": 1}},
    )
    assert resp.status_code == 422
    assert "unknown budget keys" in resp.json()["detail"]


def test_a_negative_budget_is_rejected(client):
    resp = client.post(
        "/judges",
        json={"name": "x", "provider": "mock", "model_id": "m", "budget": {"daily_usd": -5}},
    )
    assert resp.status_code == 422


def test_versioning_bumps_and_leaves_the_old_version_intact(client):
    v1 = _judge(client, prompt_template="terse")
    v2 = client.post(f"/judges/{v1['id']}:version", json={"prompt_template": "thorough"}).json()

    assert (v1["prompt_version"], v2["prompt_version"]) == (1, 2)
    assert v2["model_id"] == v1["model_id"], "unset fields carry forward"
    assert client.get(f"/judges/{v1['id']}").json()["prompt_template"] == "terse"


def test_judge_endpoints_are_admin_only(client):
    for headers in (_as(client, "rev-key"), _as(client, "ann-key")):
        assert client.get("/judges", headers=headers).status_code == 403
        assert (
            client.post(
                "/judges",
                json={"name": "x", "provider": "mock", "model_id": "m"},
                headers=headers,
            ).status_code
            == 403
        )


# --- attach + run ------------------------------------------------------------


def test_attach_then_run_writes_labels(client):
    project = _project(client)
    _units(client, project["id"], 4)
    judge = _judge(client)

    attached = client.post(f"/projects/{project['id']}/judges/{judge['id']}:attach")
    assert attached.status_code == 200
    assert attached.json()["annotator_id"]

    run = client.post(f"/projects/{project['id']}/judges:run", json={"limit": 3})
    assert run.status_code == 200
    body = run.json()
    assert body["labels_written"] == 3
    assert body["runs"][0]["stopped_reason"] == "limit"

    # K=1 and one judge: each labeled unit is unopposed, so M8's routing pipeline
    # carries it straight through to finalized (§7.2). The claim under test is
    # that three units *left the queue*, not which terminal bucket they land in.
    progress = client.get(f"/projects/{project['id']}/progress").json()
    assert progress["funnel"]["labeled"] + progress["funnel"]["finalized"] >= 3


def test_running_with_no_judges_enrolled_is_a_409(client):
    project = _project(client)
    _units(client, project["id"], 1)
    resp = client.post(f"/projects/{project['id']}/judges:run", json={})
    assert resp.status_code == 409
    assert "attach one first" in resp.json()["detail"]


def test_running_an_unattached_judge_by_id_is_a_409(client):
    project = _project(client)
    _units(client, project["id"], 1)
    judge = _judge(client)
    resp = client.post(
        f"/projects/{project['id']}/judges:run", json={"judge_config_id": judge["id"]}
    )
    assert resp.status_code == 409


def test_a_run_with_no_judge_id_runs_every_enrolled_judge(client):
    project = _project(client, labels_per_unit=2, max_labels_per_unit=2)
    _units(client, project["id"], 2)
    for name in ("judge-a", "judge-b"):
        judge = _judge(client, name=name)
        client.post(f"/projects/{project['id']}/judges/{judge['id']}:attach")

    body = client.post(f"/projects/{project['id']}/judges:run", json={}).json()
    assert len(body["runs"]) == 2
    assert body["labels_written"] == 4


def test_dry_run_reports_an_estimate_and_writes_nothing(client):
    project = _project(client)
    _units(client, project["id"], 3)
    judge = _judge(client, params={"price": {"input": 3.0, "output": 15.0}})
    client.post(f"/projects/{project['id']}/judges/{judge['id']}:attach")

    body = client.post(f"/projects/{project['id']}/judges:run", json={"dry_run": True}).json()
    assert body["dry_run"] is True
    assert body["labels_written"] == 0
    assert body["estimated_cost_usd"] > 0

    progress = client.get(f"/projects/{project['id']}/progress").json()
    assert progress["funnel"]["labeled"] == 0


def test_running_is_admin_only_but_reading_is_reviewer(client):
    project = _project(client)
    _units(client, project["id"], 2)
    judge = _judge(client)
    client.post(f"/projects/{project['id']}/judges/{judge['id']}:attach")

    assert (
        client.post(
            f"/projects/{project['id']}/judges:run", json={}, headers=_as(client, "rev-key")
        ).status_code
        == 403
    )
    client.post(f"/projects/{project['id']}/judges:run", json={})
    assert (
        client.get(
            f"/projects/{project['id']}/judge-runs", headers=_as(client, "rev-key")
        ).status_code
        == 200
    )


def test_project_judges_endpoint_reports_spend_against_caps(client):
    project = _project(client)
    _units(client, project["id"], 3)
    judge = _judge(
        client, params={"price": {"input": 100.0, "output": 100.0}}, budget={"project_usd": 5.0}
    )
    client.post(f"/projects/{project['id']}/judges/{judge['id']}:attach")
    client.post(f"/projects/{project['id']}/judges:run", json={})

    row = client.get(f"/projects/{project['id']}/judges").json()["judges"][0]
    assert row["judge_config_id"] == judge["id"]
    assert row["budget"] == {"project_usd": 5.0}
    assert row["spend"]["labels"] == 3
    assert row["spend"]["cost_usd"] > 0
    assert row["price_source"] == "config"


def test_run_history_records_dry_and_live_runs(client):
    project = _project(client)
    _units(client, project["id"], 2)
    judge = _judge(client)
    client.post(f"/projects/{project['id']}/judges/{judge['id']}:attach")
    client.post(f"/projects/{project['id']}/judges:run", json={"dry_run": True})
    client.post(f"/projects/{project['id']}/judges:run", json={})

    runs = client.get(f"/projects/{project['id']}/judge-runs").json()
    assert len(runs) == 2
    assert runs[0]["dry_run"] is False  # newest first
    assert runs[1]["dry_run"] is True


def test_detach_endpoint_removes_the_enrollment(client):
    project = _project(client)
    judge = _judge(client)
    client.post(f"/projects/{project['id']}/judges/{judge['id']}:attach")
    client.post(f"/projects/{project['id']}/judges/{judge['id']}:detach")
    assert client.get(f"/projects/{project['id']}/judges").json()["judges"] == []


# --- costs -------------------------------------------------------------------


def test_costs_endpoint_reports_per_judge_spend(client):
    project = _project(client)
    _units(client, project["id"], 4)
    judge = _judge(client, params={"price": {"input": 10.0, "output": 10.0}})
    client.post(f"/projects/{project['id']}/judges/{judge['id']}:attach")
    client.post(f"/projects/{project['id']}/judges:run", json={})

    costs = client.get(f"/projects/{project['id']}/analytics/costs").json()
    assert costs["judges"][0]["labels"] == 4
    assert costs["judges"][0]["cost_per_label"] > 0
    assert costs["totals"]["cache_hit_rate"] == 0.0


def test_costs_is_reviewer_gated_not_annotator(client):
    project = _project(client)
    assert (
        client.get(
            f"/projects/{project['id']}/analytics/costs", headers=_as(client, "rev-key")
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/projects/{project['id']}/analytics/costs", headers=_as(client, "ann-key")
        ).status_code
        == 403
    )


def test_costs_on_an_unknown_project_is_404(client):
    assert client.get("/projects/99999/analytics/costs").status_code == 404


# --- webhooks ----------------------------------------------------------------


def test_register_list_and_delete_a_webhook(client):
    created = client.post(
        "/webhooks",
        json={
            "event": "budget.cap_reached",
            "target_url": "https://hooks.test/mlp",
            "secret": "shh",
        },
    )
    assert created.status_code == 201
    hook = created.json()
    assert hook["has_secret"] is True
    assert "secret" not in hook, "a listing endpoint must never echo signing keys"

    assert any(h["id"] == hook["id"] for h in client.get("/webhooks").json())
    assert client.delete(f"/webhooks/{hook['id']}").status_code == 200
    assert client.get("/webhooks").json() == []


def test_an_unknown_event_is_rejected(client):
    resp = client.post(
        "/webhooks", json={"event": "server.on_fire", "target_url": "https://x.test/h"}
    )
    assert resp.status_code == 422


def test_a_non_http_target_is_rejected(client):
    resp = client.post(
        "/webhooks", json={"event": "project.completed", "target_url": "ftp://x.test/h"}
    )
    assert resp.status_code == 422


def test_webhook_events_endpoint_lists_the_four_events(client):
    events = client.get("/webhooks/events").json()["events"]
    assert set(events) == {
        "budget.cap_reached",
        "gold.accuracy_dropped",
        "review.queue_backlog",
        "project.completed",
    }


def test_webhook_registration_is_admin_only(client):
    resp = client.post(
        "/webhooks",
        json={"event": "project.completed", "target_url": "https://x.test/h"},
        headers=_as(client, "rev-key"),
    )
    assert resp.status_code == 403


def test_budget_cap_delivery_shows_up_in_the_delivery_log(client):
    """End-to-end: cap → stop → emit → persisted delivery, all through HTTP.

    The target is unreachable on purpose — the point is that a *failed* delivery
    is still recorded, which is what makes a silently-broken webhook visible.
    """
    project = _project(client)
    _units(client, project["id"], 5)
    client.post(
        "/webhooks",
        json={
            "event": "budget.cap_reached",
            "target_url": "http://127.0.0.1:9/blackhole",
            "project_id": project["id"],
            "secret": "k",
        },
    )
    judge = _judge(client, budget={"max_labels": 2})
    client.post(f"/projects/{project['id']}/judges/{judge['id']}:attach")

    body = client.post(f"/projects/{project['id']}/judges:run", json={}).json()
    assert body["runs"][0]["stopped_reason"] == "budget_labels"
    assert body["labels_written"] == 2

    deliveries = client.get("/webhooks/deliveries").json()
    assert len(deliveries) == 1
    assert deliveries[0]["event"] == "budget.cap_reached"
    assert deliveries[0]["payload"]["metric"]["cap_labels"] == 2
    assert deliveries[0]["status"] == "failed"
    assert deliveries[0]["attempts"] == 3
