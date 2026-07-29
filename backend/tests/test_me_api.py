"""`/me` and `/me:annotator` (§5) — the bridge from a token to a rater record.

`users` and `annotators` are separate by design (§4). These tests pin the two
things that make bridging them safe: creating happens on POST only, and it never
produces a second rater for the same user — a user with two annotator records
would split their own reputation and could label the same unit twice, defeating
the §2.7 exclusion.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import Annotator, User
from app.services.auth.roles import hash_api_key
from app.services.templates.seed import seed_templates

TRUNCATE = (
    "TRUNCATE templates, projects, batches, units, slots, labels, final_labels, "
    "users, annotators, judge_configs, judge_runs, judge_cache, reputation_events, "
    "webhooks, webhook_deliveries RESTART IDENTITY CASCADE"
)


@pytest.fixture()
def session_factory(engine):
    def make():
        return Session(bind=engine, expire_on_commit=False)

    return make


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


def _as(key):
    return {"Authorization": f"Bearer {key}"}


# --- GET /me ----------------------------------------------------------------


def test_me_identifies_the_token_holder(client):
    body = client.get("/me").json()
    assert body["email"] == "admin@x.com"
    assert body["role"] == "admin"


def test_me_reports_no_annotator_before_one_exists(client):
    assert client.get("/me").json()["annotator_id"] is None


def test_me_does_not_create_an_annotator(client, session_factory):
    """A page load must not insert rows. Creation is a POST, deliberately."""
    client.get("/me")
    client.get("/me")

    db = session_factory()
    try:
        assert db.scalars(select(Annotator)).all() == []
    finally:
        db.close()


def test_me_requires_a_token(client):
    assert client.get("/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_every_role_can_read_me(client):
    for key in ("admin-key", "rev-key", "ann-key"):
        assert client.get("/me", headers=_as(key)).status_code == 200


# --- POST /me:annotator -----------------------------------------------------


def test_creates_an_annotator_on_first_use(client):
    body = client.post("/me:annotator").json()

    assert body["kind"] == "human"
    assert body["status"] == "active"
    assert body["display_name"] == "admin"
    assert client.get("/me").json()["annotator_id"] == body["id"]


def test_is_idempotent_and_never_makes_a_second_rater(client, session_factory):
    first = client.post("/me:annotator").json()
    second = client.post("/me:annotator").json()

    assert first["id"] == second["id"]
    db = session_factory()
    try:
        assert len(db.scalars(select(Annotator)).all()) == 1
    finally:
        db.close()


def test_returns_200_not_201_because_it_is_get_or_create(client):
    assert client.post("/me:annotator").status_code == 200


def test_each_user_gets_their_own_rater(client):
    admin = client.post("/me:annotator").json()
    annotator = client.post("/me:annotator", headers=_as("ann-key")).json()

    assert admin["id"] != annotator["id"]
    assert client.get("/me", headers=_as("ann-key")).json()["annotator_id"] == annotator["id"]


def test_an_existing_annotator_is_reused_not_replaced(client, session_factory):
    """An admin who is already a rater keeps their history and reputation."""
    db = session_factory()
    try:
        user = db.scalar(select(User).where(User.email == "admin@x.com"))
        existing = Annotator(
            kind="human",
            user_id=user.id,
            display_name="Established Rater",
            reputation_score=0.87,
        )
        db.add(existing)
        db.commit()
        existing_id = existing.id
    finally:
        db.close()

    body = client.post("/me:annotator").json()

    assert body["id"] == existing_id
    assert body["display_name"] == "Established Rater"
    assert body["reputation_score"] == pytest.approx(0.87)


def test_a_model_judge_annotator_is_never_claimed_as_mine(client, session_factory):
    """Judges have no user_id; the lookup filters on kind anyway. Belt and braces:
    handing an admin a judge's rater record would attribute model labels to them."""
    from app.services.judges import attach_judge, create_judge_config

    db = session_factory()
    try:
        seed_templates(db)
        from app.models import Template
        from app.services.projects import create_project

        tmpl = db.scalar(select(Template).where(Template.name == "image-classification"))
        project = create_project(db, name="p", template_id=tmpl.id)
        config = create_judge_config(db, name="j", provider="mock", model_id="mock-1")
        attach_judge(db, project.id, config.id)
        db.commit()
    finally:
        db.close()

    mine = client.post("/me:annotator").json()
    assert mine["kind"] == "human"

    db = session_factory()
    try:
        judge = db.scalar(select(Annotator).where(Annotator.kind == "model"))
        assert judge is not None and judge.id != mine["id"]
    finally:
        db.close()


# --- the point of the endpoint ----------------------------------------------


def test_an_admin_can_go_from_token_to_labeling_in_two_calls(client):
    """The "Start labeling" button's whole backend story.

    An admin holds a user token, has no annotator id, and wants to try the
    project they just configured. Two calls and they are leasing a task.
    """
    tid = next(
        t["id"] for t in client.get("/templates").json() if t["name"] == "image-classification"
    )
    project = client.post(
        "/projects", json={"name": "try me", "template_id": tid, "gold_ratio": 0}
    ).json()
    client.post(
        f"/projects/{project['id']}/units:bulk",
        json={"jsonl": '{"payload": {"image_url": "http://x/1.png"}}', "format": "jsonl"},
    )

    annotator_id = client.post("/me:annotator").json()["id"]
    task = client.get(f"/tasks/next?annotator={annotator_id}&project={project['id']}")

    assert task.status_code == 200
    assert task.json()["unit_id"]


def test_the_new_annotator_can_submit_and_is_attributed(client):
    tid = next(
        t["id"] for t in client.get("/templates").json() if t["name"] == "image-classification"
    )
    project = client.post(
        "/projects", json={"name": "attribution", "template_id": tid, "gold_ratio": 0}
    ).json()
    client.post(
        f"/projects/{project['id']}/units:bulk",
        json={"jsonl": '{"payload": {"image_url": "http://x/1.png"}}', "format": "jsonl"},
    )
    annotator_id = client.post("/me:annotator").json()["id"]
    slot = client.get(f"/tasks/next?annotator={annotator_id}&project={project['id']}").json()

    submitted = client.post(
        f"/tasks/{slot['slot_id']}/submit?annotator={annotator_id}",
        json={"raw": {"category": "cat"}},
    )

    assert submitted.status_code == 201
    assert submitted.json()["annotator_id"] == annotator_id
    roster = client.get(f"/projects/{project['id']}/annotators").json()
    assert any(r["annotator_id"] == annotator_id for r in roster["annotators"])
