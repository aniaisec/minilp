"""End-to-end API tests through FastAPI (§5). Uses the test engine via a
dependency override so requests hit the real Postgres schema."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import Template, User
from app.services.auth.roles import hash_api_key
from app.services.templates.seed import seed_templates


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

    # Seed builtins + an admin user for the (now auth-gated) API surface.
    seeder = Session(bind=engine, expire_on_commit=False)
    seed_templates(seeder)
    seeder.add(User(email="admin@x.com", role="admin", api_key_hash=hash_api_key("admin-key")))
    seeder.commit()
    seeder.close()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer admin-key"})  # admin token by default
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


def test_health(client) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_list_templates_returns_gallery(client) -> None:
    resp = client.get("/templates")
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()}
    assert "side-by-side-preference" in names
    assert "image-classification" in names


def test_get_single_template_and_project(client) -> None:
    """The annotation UI's first two calls on page load (§11). Regression: these
    routes were missing through M4 — the UI 404'd on every project URL."""
    tid = client.get("/templates").json()[0]["id"]
    t = client.get(f"/templates/{tid}")
    assert t.status_code == 200
    assert t.json()["id"] == tid

    proj = client.post(
        "/projects", json={"name": "p", "template_id": tid, "labels_per_unit": 1}
    ).json()
    p = client.get(f"/projects/{proj['id']}")
    assert p.status_code == 200
    assert p.json()["template_id"] == tid
    assert "guidelines_md" in p.json()

    assert client.get("/templates/99999").status_code == 404
    assert client.get("/projects/99999").status_code == 404


def test_create_invalid_template_returns_422(client) -> None:
    resp = client.post("/templates", json={"schema": {"name": "x", "inputs": []}})
    assert resp.status_code == 422
    assert "errors" in resp.json()["detail"]


def test_clone_and_preview_flow(client, engine) -> None:
    templates = client.get("/templates").json()
    builtin = next(t for t in templates if t["name"] == "image-classification")

    clone = client.post(f"/templates/{builtin['id']}:clone", json={"new_name": "my-img"})
    assert clone.status_code == 201
    clone_body = clone.json()
    assert clone_body["kind"] == "custom"

    preview = client.post(
        f"/templates/{clone_body['id']}/preview",
        json={"payload": {"image_url": "http://x/1.png"}},
    )
    assert preview.status_code == 200
    assert preview.json()["payload_valid"] is True

    # original builtin untouched
    with Session(bind=engine) as s:
        orig = s.get(Template, builtin["id"])
        assert orig.kind == "builtin"


def test_project_and_bulk_ingest_flow(client) -> None:
    templates = client.get("/templates").json()
    sbs = next(t for t in templates if t["name"] == "side-by-side-preference")

    # non-divisible K rejected
    bad = client.post(
        "/projects", json={"name": "bad", "template_id": sbs["id"], "labels_per_unit": 3}
    )
    assert bad.status_code == 422

    proj = client.post(
        "/projects",
        json={"name": "sbs-proj", "template_id": sbs["id"], "labels_per_unit": 4},
    ).json()

    jsonl = "\n".join(
        [
            '{"payload": {"prompt": "p1", "response_a": "a", "response_b": "b"}}',
            "{bad json",
            '{"payload": {"prompt": "p2", "response_a": "a", "response_b": "b"}}',
        ]
    )
    report = client.post(f"/projects/{proj['id']}/units:bulk", json={"jsonl": jsonl}).json()
    assert report["unit_count"] == 2
    assert report["rejected_count"] == 1
    assert report["rejected_rows"][0]["row"] == 2

    units = client.get(f"/projects/{proj['id']}/units").json()
    assert len(units) == 2
