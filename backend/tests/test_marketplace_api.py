"""Marketplace endpoints through FastAPI (§5, §12, M10): export a template /
judge config / project as a bundle, browse the shipped local directory, and
import a bundle back in — admin-only throughout, the same bucket as templates
and judges."""

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


def _template_id(client, name="side-by-side-preference"):
    return next(t["id"] for t in client.get("/templates").json() if t["name"] == name)


def _judge(client, **kwargs):
    body = {"name": "mock-judge", "provider": "mock", "model_id": "mock-1"}
    body.update(kwargs)
    return client.post("/judges", json=body).json()


def _project(client, *, template="image-classification", **kwargs):
    tid = _template_id(client, template)
    body = {"name": "bundled", "template_id": tid, "labels_per_unit": 1, "gold_ratio": 0.0}
    body.update(kwargs)
    return client.post("/projects", json=body).json()


# --- export endpoints ---------------------------------------------------------


def test_template_export_returns_a_bundle(client):
    tid = _template_id(client)
    bundle = client.get(f"/templates/{tid}:export").json()
    assert bundle["kind"] == "template"
    assert bundle["template"]["name"] == "side-by-side-preference"


def test_template_export_on_an_unknown_id_is_404(client):
    assert client.get("/templates/99999:export").status_code == 404


def test_judge_config_export_returns_a_bundle_with_no_credential(client):
    judge = _judge(client, params={"api_key_env": "OPENAI_API_KEY"})
    bundle = client.get(f"/judges/{judge['id']}:export").json()
    assert bundle["kind"] == "judge_config"
    assert bundle["judge_config"]["params"]["api_key_env"] == "OPENAI_API_KEY"
    assert "sk-" not in str(bundle)


def test_project_bundle_export_carries_template_and_judges_not_units(client):
    project = _project(client)
    judge = _judge(client)
    client.post(f"/projects/{project['id']}/judges/{judge['id']}:attach")
    rows = "\n".join([f'{{"payload": {{"image_url": "http://x/{i}.png"}}}}' for i in range(3)])
    client.post(f"/projects/{project['id']}/units:bulk", json={"jsonl": rows, "format": "jsonl"})

    bundle = client.get(f"/projects/{project['id']}:export-bundle").json()
    assert bundle["kind"] == "project"
    assert bundle["template"]["name"] == "image-classification"
    assert len(bundle["judge_configs"]) == 1
    assert "units" not in bundle


def test_export_endpoints_are_admin_only(client):
    tid = _template_id(client)
    judge = _judge(client)
    project = _project(client)
    for headers in (_as(client, "rev-key"), _as(client, "ann-key")):
        assert client.get(f"/templates/{tid}:export", headers=headers).status_code == 403
        assert client.get(f"/judges/{judge['id']}:export", headers=headers).status_code == 403
        assert (
            client.get(f"/projects/{project['id']}:export-bundle", headers=headers).status_code
            == 403
        )


# --- import ---------------------------------------------------------------------


def test_export_then_import_round_trips_through_http(client):
    tid = _template_id(client, "image-classification")
    bundle = client.get(f"/templates/{tid}:export").json()

    imported = client.post("/marketplace/import", json={"bundle": bundle})
    assert imported.status_code == 201
    body = imported.json()
    assert body["kind"] == "template"
    new_id = body["template"]["id"]
    assert new_id != tid

    # The imported template is real and previews like any other (M1 guarantee).
    sample = client.get(f"/templates/{new_id}/sample").json()
    preview = client.post(f"/templates/{new_id}/preview", json={"payload": sample["sample"]})
    assert preview.status_code == 200
    assert preview.json()["payload_valid"] is True


def test_importing_a_project_bundle_creates_a_working_project(client):
    project = _project(client)
    judge = _judge(client)
    client.post(f"/projects/{project['id']}/judges/{judge['id']}:attach")
    bundle = client.get(f"/projects/{project['id']}:export-bundle").json()

    imported = client.post("/marketplace/import", json={"bundle": bundle}).json()
    new_project_id = imported["project"]["id"]
    assert new_project_id != project["id"]

    judges = client.get(f"/projects/{new_project_id}/judges").json()["judges"]
    assert len(judges) == 1
    assert judges[0]["judge_config_id"] != judge["id"]


def test_importing_a_project_bundle_without_create_project_skips_the_project(client):
    project = _project(client)
    bundle = client.get(f"/projects/{project['id']}:export-bundle").json()

    imported = client.post(
        "/marketplace/import", json={"bundle": bundle, "create_project": False}
    ).json()
    assert "project" not in imported
    assert imported["template"]["id"] is not None


def test_importing_a_malformed_bundle_is_a_422_with_the_real_validation_errors(client):
    resp = client.post(
        "/marketplace/import",
        json={
            "bundle": {
                "bundle_version": 1,
                "kind": "template",
                "template": {
                    "name": "bad",
                    "inputs": [{"id": "x", "type": "radio", "options": ["only-one"]}],
                },
            }
        },
    )
    assert resp.status_code == 422
    assert "errors" in resp.json()["detail"]


def test_importing_an_unknown_provider_judge_bundle_is_422(client):
    resp = client.post(
        "/marketplace/import",
        json={
            "bundle": {
                "bundle_version": 1,
                "kind": "judge_config",
                "judge_config": {"name": "x", "provider": "vibes", "model_id": "m"},
            }
        },
    )
    assert resp.status_code == 422


def test_importing_an_unsupported_bundle_version_is_422(client):
    resp = client.post(
        "/marketplace/import",
        json={"bundle": {"bundle_version": 999, "kind": "template", "template": {}}},
    )
    assert resp.status_code == 422


def test_import_is_admin_only(client):
    tid = _template_id(client)
    bundle = client.get(f"/templates/{tid}:export").json()
    for headers in (_as(client, "rev-key"), _as(client, "ann-key")):
        resp = client.post("/marketplace/import", json={"bundle": bundle}, headers=headers)
        assert resp.status_code == 403


# --- the local shared-bundle directory -------------------------------------------


def test_local_bundles_are_listed(client):
    bundles = client.get("/marketplace/bundles").json()["bundles"]
    filenames = {b["filename"] for b in bundles}
    assert "toxicity-triage.json" in filenames
    assert "summarization-quality.json" in filenames
    assert "calibrated-mock-judge.json" in filenames


def test_a_local_bundle_can_be_read_then_imported_by_filename(client):
    full = client.get("/marketplace/bundles/summarization-quality.json")
    assert full.status_code == 200
    assert full.json()["kind"] == "template"

    imported = client.post("/marketplace/bundles/summarization-quality.json:import")
    assert imported.status_code == 201
    assert imported.json()["kind"] == "template"


def test_importing_the_project_starter_kit_by_filename_creates_a_project(client):
    imported = client.post("/marketplace/bundles/toxicity-triage.json:import")
    assert imported.status_code == 201
    body = imported.json()
    assert body["kind"] == "project"
    assert body["project"]["id"] is not None
    assert len(body["judge_configs"]) == 1


def test_reading_an_unknown_local_bundle_is_404(client):
    assert client.get("/marketplace/bundles/does-not-exist.json").status_code == 404


def test_local_bundle_listing_and_import_are_admin_only(client):
    for headers in (_as(client, "rev-key"), _as(client, "ann-key")):
        assert client.get("/marketplace/bundles", headers=headers).status_code == 403
        assert (
            client.post(
                "/marketplace/bundles/toxicity-triage.json:import", headers=headers
            ).status_code
            == 403
        )
