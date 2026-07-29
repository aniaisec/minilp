"""Deleting templates (§2.5) — service + API, against real PostgreSQL.

A template is the definition of every label collected under it, so the whole
feature is really three refusals and one deletion. The refusals get more tests
than the deletion, because a delete that succeeds when it should not is the only
failure mode here that loses data.
"""

import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import Project, Slot, Template, Unit, User
from app.services.auth.roles import hash_api_key
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.templates.repository import (
    TemplateError,
    TemplateInUseError,
    clone_template,
    create_template,
    delete_template,
    edit_template,
    template_usage,
)
from app.services.templates.seed import IMAGE_CLASSIFICATION, seed_templates

# --- helpers ----------------------------------------------------------------


def _custom(db, name="throwaway"):
    schema = copy.deepcopy(IMAGE_CLASSIFICATION)
    schema["name"] = name
    return create_template(db, schema)


def _builtin(db, name="image-classification"):
    seed_templates(db)
    return db.scalar(select(Template).where(Template.name == name))


# --- the deletion that works ------------------------------------------------


def test_deletes_an_unused_custom_template(db):
    tmpl = _custom(db)
    tid = tmpl.id

    result = delete_template(db, tid)

    assert result["count"] == 1
    assert result["deleted"] == [{"id": tid, "name": "throwaway", "version": 1}]
    assert db.get(Template, tid) is None


def test_deleting_one_version_leaves_the_others(db):
    v1 = _custom(db, "iterated")
    schema = copy.deepcopy(v1.schema)
    schema["inputs"][0]["options"] = ["cat", "dog", "bird", "fish"]  # schema-affecting
    v2 = edit_template(db, v1.id, schema)
    assert (v1.version, v2.version) == (1, 2)

    delete_template(db, v1.id)

    assert db.get(Template, v1.id) is None
    assert db.get(Template, v2.id) is not None


def test_deleting_the_lineage_removes_every_version(db):
    v1 = _custom(db, "iterated")
    schema = copy.deepcopy(v1.schema)
    schema["inputs"][0]["options"] = ["cat", "dog", "bird", "fish"]
    v2 = edit_template(db, v1.id, schema)

    result = delete_template(db, v2.id, all_versions=True)

    assert result["count"] == 2
    assert db.get(Template, v1.id) is None
    assert db.get(Template, v2.id) is None


def test_deleting_a_clone_never_touches_its_source(db):
    """Cloning is how you 'edit' a builtin; deleting the copy must be safe."""
    src = _builtin(db)
    draft = clone_template(db, src.id, new_name="my copy")

    delete_template(db, draft.id)

    assert db.get(Template, src.id) is not None
    assert db.get(Template, draft.id) is None


# --- refusal 1: builtins ----------------------------------------------------


def test_refuses_to_delete_a_builtin(db):
    """Same rule that makes edit_template refuse: clone instead.

    A builtin delete would also silently undo itself — the seeder recreates the
    gallery on the next boot — and a delete that does not stay deleted is worse
    than one that says no.
    """
    builtin = _builtin(db)
    with pytest.raises(TemplateError, match="builtin"):
        delete_template(db, builtin.id)
    assert db.get(Template, builtin.id) is not None


def test_lineage_delete_of_a_builtin_is_refused_too(db):
    builtin = _builtin(db)
    with pytest.raises(TemplateError, match="builtin"):
        delete_template(db, builtin.id, all_versions=True)


def test_a_lineage_delete_skips_builtins_sharing_the_name(db):
    """A custom clone that kept the builtin's name must not drag the builtin out.

    Contrived, but the lineage query is name-based, and 'delete everything called
    X' quietly including a builtin X is exactly the kind of thing that only shows
    up in production.
    """
    builtin = _builtin(db)
    draft = clone_template(db, builtin.id, new_name=builtin.name + " (copy)")
    draft.name = builtin.name  # force the name collision the constraint allows
    draft.version = 99
    db.flush()

    result = delete_template(db, draft.id, all_versions=True)

    assert result["count"] == 1
    assert db.get(Template, builtin.id) is not None


# --- refusal 2: in use ------------------------------------------------------


def test_refuses_to_delete_a_template_a_project_uses_and_names_it(db):
    tmpl = _custom(db, "in-use")
    project = create_project(db, name="Q3 preference run", template_id=tmpl.id)

    with pytest.raises(TemplateInUseError) as e:
        delete_template(db, tmpl.id)

    assert "Q3 preference run" in str(e.value)
    assert f"#{project.id}" in str(e.value)
    assert e.value.blockers[0]["project_id"] == project.id
    assert db.get(Template, tmpl.id) is not None


def test_a_lineage_delete_is_all_or_nothing(db):
    """If any version is in use, nothing is deleted.

    A partial lineage delete leaves history with holes and the caller believing
    it worked.
    """
    v1 = _custom(db, "iterated")
    schema = copy.deepcopy(v1.schema)
    schema["inputs"][0]["options"] = ["cat", "dog", "bird", "fish"]
    v2 = edit_template(db, v1.id, schema)
    create_project(db, name="uses v1", template_id=v1.id)

    with pytest.raises(TemplateInUseError):
        delete_template(db, v2.id, all_versions=True)

    assert db.get(Template, v1.id) is not None
    assert db.get(Template, v2.id) is not None, "the unused version must not vanish either"


def test_an_unused_version_is_still_deletable_while_a_sibling_is_in_use(db):
    """Per-version delete is per-version: only the lineage delete is all-or-nothing."""
    v1 = _custom(db, "iterated")
    schema = copy.deepcopy(v1.schema)
    schema["inputs"][0]["options"] = ["cat", "dog", "bird", "fish"]
    v2 = edit_template(db, v1.id, schema)
    create_project(db, name="uses v1", template_id=v1.id)

    delete_template(db, v2.id)

    assert db.get(Template, v2.id) is None
    assert db.get(Template, v1.id) is not None


def test_deleting_the_project_frees_the_template(db):
    tmpl = _custom(db, "freed")
    project = create_project(db, name="temporary", template_id=tmpl.id)
    with pytest.raises(TemplateInUseError):
        delete_template(db, tmpl.id)

    db.delete(project)
    db.flush()

    delete_template(db, tmpl.id)
    assert db.get(Template, tmpl.id) is None


def test_collected_labels_are_never_orphaned(db):
    """The reason the refusal exists, stated as a test.

    A project with real labels blocks the delete; the labels, slots and units are
    all still there afterwards.
    """
    tmpl = _custom(db, "collected")
    project = create_project(db, name="live work", template_id=tmpl.id, gold_ratio=0.0)
    ingest_units(db, project, parse_jsonl('{"payload": {"image_url": "http://x/1.png"}}'))
    user = User(email="a@x.io", role="annotator")
    db.add(user)
    db.flush()

    with pytest.raises(TemplateInUseError):
        delete_template(db, tmpl.id)

    assert db.scalar(select(Unit).where(Unit.project_id == project.id)) is not None
    assert db.scalar(select(Slot)) is not None
    assert db.get(Project, project.id) is not None


# --- refusal 3: missing -----------------------------------------------------


def test_deleting_a_missing_template_is_a_not_found_error(db):
    with pytest.raises(TemplateError, match="not found"):
        delete_template(db, 999_999)


# --- usage report -----------------------------------------------------------


def test_template_usage_lists_the_bound_projects(db):
    tmpl = _custom(db, "counted")
    a = create_project(db, name="one", template_id=tmpl.id)
    b = create_project(db, name="two", template_id=tmpl.id)

    usage = template_usage(db, [tmpl.id])

    assert {u["project_id"] for u in usage} == {a.id, b.id}
    assert template_usage(db, []) == []


# --- API --------------------------------------------------------------------

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


def _make_custom(client, name="api-throwaway"):
    schema = copy.deepcopy(IMAGE_CLASSIFICATION)
    schema["name"] = name
    return client.post("/templates", json={"schema": schema}).json()


def test_delete_endpoint_removes_an_unused_custom_template(client):
    tmpl = _make_custom(client)

    resp = client.delete(f"/templates/{tmpl['id']}")

    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert client.get(f"/templates/{tmpl['id']}").status_code == 404
    assert all(t["id"] != tmpl["id"] for t in client.get("/templates").json())


def test_delete_endpoint_refuses_a_builtin_with_409(client):
    builtin = next(t for t in client.get("/templates").json() if t["kind"] == "builtin")

    resp = client.delete(f"/templates/{builtin['id']}")

    assert resp.status_code == 409
    assert "clone" in resp.json()["detail"]
    assert client.get(f"/templates/{builtin['id']}").status_code == 200


def test_delete_endpoint_refuses_an_in_use_template_and_returns_the_blockers(client):
    tmpl = _make_custom(client, "api-in-use")
    project = client.post(
        "/projects", json={"name": "Autumn eval", "template_id": tmpl["id"]}
    ).json()

    resp = client.delete(f"/templates/{tmpl['id']}")

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "Autumn eval" in detail["message"]
    assert detail["blockers"][0]["project_id"] == project["id"]
    assert detail["blockers"][0]["name"] == "Autumn eval"


def test_delete_endpoint_404s_on_a_missing_template(client):
    assert client.delete("/templates/999999").status_code == 404


def test_delete_endpoint_rejects_a_bad_versions_value(client):
    tmpl = _make_custom(client)
    assert client.delete(f"/templates/{tmpl['id']}?versions=some").status_code == 422


def test_delete_endpoint_can_remove_a_whole_lineage(client):
    tmpl = _make_custom(client, "api-iterated")
    schema = copy.deepcopy(tmpl["schema"])
    schema["inputs"][0]["options"] = ["cat", "dog", "bird", "fish"]
    v2 = client.put(f"/templates/{tmpl['id']}", json={"schema": schema}).json()
    assert v2["version"] == 2

    resp = client.delete(f"/templates/{v2['id']}?versions=all")

    assert resp.json()["count"] == 2
    assert client.get(f"/templates/{tmpl['id']}").status_code == 404
    assert client.get(f"/templates/{v2['id']}").status_code == 404


def test_delete_is_admin_only(client):
    tmpl = _make_custom(client)
    for key in ("rev-key", "ann-key"):
        resp = client.delete(f"/templates/{tmpl['id']}", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 403
    assert client.get(f"/templates/{tmpl['id']}").status_code == 200


def test_usage_endpoint_explains_why_a_template_is_not_deletable(client):
    tmpl = _make_custom(client, "api-usage")
    assert client.get(f"/templates/{tmpl['id']}/usage").json()["deletable"] is True

    client.post("/projects", json={"name": "blocker", "template_id": tmpl["id"]})
    usage = client.get(f"/templates/{tmpl['id']}/usage").json()

    assert usage["deletable"] is False
    assert usage["projects"][0]["name"] == "blocker"
    assert usage["versions"] == 1


def test_usage_endpoint_marks_builtins_undeletable(client):
    builtin = next(t for t in client.get("/templates").json() if t["kind"] == "builtin")
    usage = client.get(f"/templates/{builtin['id']}/usage").json()
    assert usage["kind"] == "builtin"
    assert usage["deletable"] is False


def test_deleted_template_no_longer_answers_sample_or_preview(client):
    """A dangling id must 404, not serve a stale schema from somewhere."""
    tmpl = _make_custom(client, "api-gone")
    client.delete(f"/templates/{tmpl['id']}")

    assert client.get(f"/templates/{tmpl['id']}/sample").status_code == 404
    assert client.post(f"/templates/{tmpl['id']}/preview", json={"payload": {}}).status_code == 404
    assert client.get(f"/templates/{tmpl['id']}/usage").status_code == 404


def test_a_project_created_after_a_failed_delete_still_works(client):
    """The refusal must not leave the session or the row in a broken state."""
    tmpl = _make_custom(client, "api-recovers")
    client.post("/projects", json={"name": "first", "template_id": tmpl["id"]})
    assert client.delete(f"/templates/{tmpl['id']}").status_code == 409

    second = client.post("/projects", json={"name": "second", "template_id": tmpl["id"]})
    assert second.status_code == 201
    assert client.get(f"/templates/{tmpl['id']}").status_code == 200


def test_labels_survive_a_refused_delete(client):
    """End-to-end version of the invariant: nothing collected is put at risk."""
    tmpl = _make_custom(client, "api-collected")
    project = client.post(
        "/projects", json={"name": "live", "template_id": tmpl["id"], "gold_ratio": 0}
    ).json()
    client.post(
        f"/projects/{project['id']}/units:bulk",
        json={"jsonl": '{"payload": {"image_url": "http://x/1.png"}}', "format": "jsonl"},
    )

    assert client.delete(f"/templates/{tmpl['id']}").status_code == 409

    units = client.get(f"/projects/{project['id']}/units").json()
    assert len(units) == 1
