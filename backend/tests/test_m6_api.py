"""M6 endpoints through FastAPI (§5): project edit, add tasks, export, builder save.

The wire-level counterpart to ``test_project_edit`` / ``test_export`` — role
gating, status codes and the exact JSON the admin UI consumes.
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
    seeder.add(worker)
    seeder.flush()
    seeder.add(Annotator(kind="human", user_id=worker.id, display_name="worker"))
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


@pytest.fixture()
def engine_session(engine):
    s = Session(bind=engine, expire_on_commit=False)
    yield s
    s.close()


def _template_id(engine_session, name="image-classification") -> int:
    return engine_session.scalar(select(Template.id).where(Template.name == name))


def _make_project(client, engine_session, **kwargs) -> dict:
    body = {
        "name": "M6 project",
        "template_id": _template_id(engine_session),
        "labels_per_unit": 1,
        "max_labels_per_unit": 4,
        **kwargs,
    }
    res = client.post("/projects", json=body)
    assert res.status_code == 201, res.text
    return res.json()


# --- PATCH /projects/{id} (§2.5 third entry point) --------------------------


def test_patch_updates_guidelines_and_k(client, engine_session) -> None:
    project = _make_project(client, engine_session)
    client.post(
        f"/projects/{project['id']}/units:bulk",
        json={"jsonl": json.dumps({"payload": {"image_url": "http://x/1.png"}}), "format": "jsonl"},
    )

    res = client.patch(
        f"/projects/{project['id']}",
        json={"guidelines_md": "# Read me", "labels_per_unit": 3},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["project"]["guidelines_md"] == "# Read me"
    assert body["project"]["labels_per_unit"] == 3
    assert body["slots_changed"] == 2
    assert body["rebound"] is False


def test_patch_with_an_edited_schema_rebinds_to_a_clone(client, engine_session) -> None:
    project = _make_project(client, engine_session)
    original_tid = project["template_id"]
    schema = client.get(f"/templates/{original_tid}").json()["schema"]
    schema["inputs"].append(
        {"id": "severity", "type": "slider", "label": "Severity", "min": 0, "max": 5, "step": 1}
    )

    res = client.patch(f"/projects/{project['id']}", json={"template_schema": schema})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["rebound"] is True
    assert body["project"]["template_id"] != original_tid

    # The gallery original still has its original inputs.
    original = client.get(f"/templates/{original_tid}").json()
    assert all(i["id"] != "severity" for i in original["schema"]["inputs"])


def test_patch_rejects_an_invalid_schema_with_all_errors(client, engine_session) -> None:
    project = _make_project(client, engine_session)
    schema = client.get(f"/templates/{project['template_id']}").json()["schema"]
    schema["inputs"].append({"id": "bad", "type": "slider", "label": "no bounds"})

    res = client.patch(f"/projects/{project['id']}", json={"template_schema": schema})
    assert res.status_code == 422
    assert any("requires both min and max" in e for e in res.json()["detail"]["errors"])


def test_patch_is_admin_only(client, engine_session) -> None:
    project = _make_project(client, engine_session)
    res = client.patch(
        f"/projects/{project['id']}",
        json={"guidelines_md": "nope"},
        headers={"Authorization": f"Bearer {ANNOTATOR_KEY}"},
    )
    assert res.status_code == 403


# --- add tasks to a live project (§5 units:bulk on an existing project) -----


def test_add_tasks_appends_a_batch_with_a_gold(client, engine_session) -> None:
    project = _make_project(client, engine_session, gold_ratio=0.5)
    first = client.post(
        f"/projects/{project['id']}/units:bulk",
        json={
            "jsonl": json.dumps({"payload": {"image_url": "http://x/1.png"}}),
            "format": "jsonl",
            "batch_name": "first",
        },
    ).json()

    second = client.post(
        f"/projects/{project['id']}/units:bulk",
        json={
            "jsonl": json.dumps(
                {
                    "payload": {"image_url": "http://x/2.png"},
                    "is_gold": True,
                    "gold_expected": {"category": "cat"},
                }
            ),
            "format": "jsonl",
            "batch_name": "second",
        },
    ).json()

    assert second["batch_id"] != first["batch_id"]
    assert second["unit_count"] == 1
    assert second["rejected_count"] == 0

    batches = client.get(f"/projects/{project['id']}/batches").json()
    assert [b["name"] for b in batches] == ["first", "second"]
    golds = client.get(f"/projects/{project['id']}/units?is_gold=true").json()
    assert len(golds) == 1


def test_add_tasks_reports_bad_rows_by_line_number(client, engine_session) -> None:
    project = _make_project(client, engine_session)
    payload = "\n".join(
        [
            json.dumps({"payload": {"image_url": "http://x/1.png"}}),
            json.dumps({"payload": {}}),
            json.dumps({"payload": {"image_url": "http://x/3.png"}, "is_gold": True}),
        ]
    )
    report = client.post(
        f"/projects/{project['id']}/units:bulk", json={"jsonl": payload, "format": "jsonl"}
    ).json()
    # Row 2 misses a required payload field; row 3 is flagged gold with nothing
    # to grade against. Both are rejected by line number; row 1 still lands.
    assert report["unit_count"] == 1
    assert report["rejected_count"] == 2
    assert [r["row"] for r in report["rejected_rows"]] == [2, 3]
    assert "image_url" in report["rejected_rows"][0]["errors"][0]
    assert "gold_expected" in report["rejected_rows"][1]["errors"][0]


# --- GET /projects/{id}/export (§10) ----------------------------------------


def test_export_streams_jsonl(client, engine_session) -> None:
    project = _make_project(client, engine_session)
    client.post(
        f"/projects/{project['id']}/units:bulk",
        json={"jsonl": json.dumps({"payload": {"image_url": "http://x/1.png"}}), "format": "jsonl"},
    )
    res = client.get(f"/projects/{project['id']}/export?format=labels")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/x-ndjson")
    assert "attachment" in res.headers["content-disposition"]
    lines = [line for line in res.text.splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["payload"] == {"image_url": "http://x/1.png"}


def test_export_rejects_an_unknown_format(client, engine_session) -> None:
    project = _make_project(client, engine_session)
    assert client.get(f"/projects/{project['id']}/export?format=parquet").status_code == 422


def test_export_of_the_wrong_shape_is_a_422_not_a_truncated_file(client, engine_session) -> None:
    """A preference export of a classification project fails *before* the response
    body starts, so a caller never saves half a file and thinks it worked."""
    project = _make_project(client, engine_session)
    res = client.get(f"/projects/{project['id']}/export?format=preference")
    assert res.status_code == 422
    assert "comparison template" in res.json()["detail"]


def test_export_is_reviewer_gated(client, engine_session) -> None:
    project = _make_project(client, engine_session)
    res = client.get(
        f"/projects/{project['id']}/export?format=labels",
        headers={"Authorization": f"Bearer {ANNOTATOR_KEY}"},
    )
    assert res.status_code == 403


# --- the builder writes ordinary templates ----------------------------------


BUILDER_OUTPUT = {
    "name": "Built in the visual builder",
    "description": "One of every M6 field type.",
    "layout": {"arrangement": "split", "ratio": [2, 1], "width": "xl"},
    "display": [
        {"type": "markdown", "source": "$unit.prompt", "render": {"collapsible": True}},
        {
            "type": "image",
            "source": "$unit.image_url",
            "optional": True,
            "render": {"fit": "contain"},
        },
    ],
    "inputs": [
        {
            "id": "verdict",
            "type": "radio",
            "label": "Verdict",
            "options": ["ok", "bad"],
            "required": True,
        },
        {"id": "score", "type": "rating", "label": "Quality", "scale": {"min": 1, "max": 5}},
        {
            "id": "confidence",
            "type": "slider",
            "label": "Confidence",
            "min": 0,
            "max": 1,
            "step": 0.1,
        },
        {"id": "topics", "type": "tags", "label": "Topics"},
        {"id": "priority", "type": "ranking", "label": "Rank these", "options": ["a", "b", "c"]},
        {"id": "reviewed_on", "type": "date", "label": "Reviewed on"},
        {"id": "escalate", "type": "boolean", "label": "Escalate?"},
    ],
    "variants": None,
}


def test_a_builder_built_template_saves_previews_and_runs_a_project(client, engine_session) -> None:
    """§12 M6 acceptance: build a template from scratch, create a project on it."""
    created = client.post("/templates", json={"schema": BUILDER_OUTPUT})
    assert created.status_code == 201, created.text
    template = created.json()

    # It previews through the same endpoint the gallery and editor use.
    preview = client.post(
        f"/templates/{template['id']}/preview",
        json={"payload": {"prompt": "Look at this", "image_url": "http://x/1.png"}},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["payload_valid"] is True
    assert [i["id"] for i in body["inputs"]] == [i["id"] for i in BUILDER_OUTPUT["inputs"]]
    assert body["inputs"][1]["value_shape"] == "int"  # rating
    assert body["inputs"][2]["value_shape"] == "number"  # slider

    # And a project runs on it end to end.
    project = client.post(
        "/projects",
        json={"name": "built", "template_id": template["id"], "labels_per_unit": 1},
    )
    assert project.status_code == 201, project.text
    report = client.post(
        f"/projects/{project.json()['id']}/units:bulk",
        json={
            "jsonl": json.dumps({"payload": {"prompt": "Look at this"}}),
            "format": "jsonl",
        },
    ).json()
    assert report["unit_count"] == 1


def test_the_builder_cannot_save_a_conflicting_hotkey(client) -> None:
    """§12 invariant 4: conflicts fail at save time, not at annotation time."""
    schema = json.loads(json.dumps(BUILDER_OUTPUT))
    schema["name"] = "conflicting"
    schema["inputs"][0]["hotkeys"] = ["s", "1"]  # 's' is reserved for skip
    res = client.post("/templates", json={"schema": schema})
    assert res.status_code == 422
    assert any("reserved key" in e for e in res.json()["detail"]["errors"])
