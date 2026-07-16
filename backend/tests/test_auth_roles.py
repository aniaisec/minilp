"""Auth + role gating (M2, §5).

Pure helpers are tested directly; endpoint gating goes through FastAPI so the
dependency wiring (header parsing, 401 vs 403) is exercised end to end. The key
acceptance point: an annotator token cannot reach admin endpoints.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import Annotator, Template, User
from app.services.auth.roles import ROLE_RANK, hash_api_key, role_allowed
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.templates.seed import seed_templates

# --- pure helpers -----------------------------------------------------------


def test_hash_api_key_deterministic_and_hex() -> None:
    h = hash_api_key("secret")
    assert h == hash_api_key("secret")
    assert h != hash_api_key("other")
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def test_role_allowed_is_rank_inclusive() -> None:
    assert ROLE_RANK["admin"] > ROLE_RANK["reviewer"] > ROLE_RANK["annotator"]
    # {"annotator"} admits everyone at or above annotator.
    assert role_allowed("admin", {"annotator"})
    assert role_allowed("reviewer", {"annotator"})
    assert role_allowed("annotator", {"annotator"})
    # {"admin"} admits only admin.
    assert role_allowed("admin", {"admin"})
    assert not role_allowed("reviewer", {"admin"})
    assert not role_allowed("annotator", {"admin"})
    assert not role_allowed("nobody", {"annotator"})


# --- endpoint gating --------------------------------------------------------


@pytest.fixture()
def api(engine):
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
    admin = User(email="admin@x.com", role="admin", api_key_hash=hash_api_key("admin-key"))
    au = User(email="ann@x.com", role="annotator", api_key_hash=hash_api_key("ann-key"))
    ou = User(email="other@x.com", role="annotator", api_key_hash=hash_api_key("other-key"))
    seeder.add_all([admin, au, ou])
    seeder.flush()
    ann = Annotator(kind="human", user_id=au.id, display_name="ann")
    other = Annotator(kind="human", user_id=ou.id, display_name="other")
    seeder.add_all([ann, other])
    seeder.flush()
    tmpl = seeder.scalar(select(Template).where(Template.name == "text-sentiment"))
    proj = create_project(seeder, name="p", template_id=tmpl.id, labels_per_unit=1)
    ingest_units(seeder, proj, parse_jsonl('{"payload": {"text": "hi"}}'))
    ctx = SimpleNamespace(project_id=proj.id, ann_id=ann.id, other_id=other.id)
    seeder.commit()
    seeder.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), ctx
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


def _h(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def test_missing_key_is_401(api) -> None:
    client, _ = api
    assert client.get("/templates").status_code == 401


def test_invalid_key_is_401(api) -> None:
    client, _ = api
    assert client.get("/templates", headers=_h("nope")).status_code == 401


def test_annotator_cannot_hit_admin_endpoint(api) -> None:
    client, ctx = api
    # Creating a project is admin-only.
    resp = client.post(
        "/projects",
        json={"name": "x", "template_id": 1, "labels_per_unit": 1},
        headers=_h("ann-key"),
    )
    assert resp.status_code == 403


def test_admin_can_hit_admin_endpoint(api) -> None:
    client, _ = api
    tmpl_id = client.get("/templates", headers=_h("admin-key")).json()[0]["id"]
    resp = client.post(
        "/projects",
        json={"name": "x", "template_id": tmpl_id, "labels_per_unit": 1},
        headers=_h("admin-key"),
    )
    assert resp.status_code == 201


def test_annotator_can_read_templates(api) -> None:
    client, _ = api
    assert client.get("/templates", headers=_h("ann-key")).status_code == 200


def test_annotator_gets_own_task(api) -> None:
    client, ctx = api
    resp = client.get(
        f"/tasks/next?annotator={ctx.ann_id}&project={ctx.project_id}",
        headers=_h("ann-key"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == ctx.project_id
    assert "is_gold" not in body  # golds stay indistinguishable


def test_annotator_cannot_act_as_another(api) -> None:
    client, ctx = api
    resp = client.get(
        f"/tasks/next?annotator={ctx.other_id}&project={ctx.project_id}",
        headers=_h("ann-key"),
    )
    assert resp.status_code == 403


def test_task_next_submit_flow_over_api(api) -> None:
    client, ctx = api
    task = client.get(
        f"/tasks/next?annotator={ctx.ann_id}&project={ctx.project_id}", headers=_h("ann-key")
    ).json()
    submit = client.post(
        f"/tasks/{task['slot_id']}/submit?annotator={ctx.ann_id}",
        json={"raw": {"sentiment": "positive"}},
        headers=_h("ann-key"),
    )
    assert submit.status_code == 201
    assert submit.json()["value"] == {"sentiment": "positive"}
    # Queue now empty for this annotator (single unit, K=1) → 204.
    empty = client.get(
        f"/tasks/next?annotator={ctx.ann_id}&project={ctx.project_id}", headers=_h("ann-key")
    )
    assert empty.status_code == 204


def test_task_skip_reopens_over_api(api) -> None:
    client, ctx = api
    task = client.get(
        f"/tasks/next?annotator={ctx.ann_id}&project={ctx.project_id}", headers=_h("ann-key")
    ).json()
    skip = client.post(
        f"/tasks/{task['slot_id']}/skip?annotator={ctx.ann_id}", headers=_h("ann-key")
    )
    assert skip.status_code == 200
    assert skip.json()["status"] == "open"
