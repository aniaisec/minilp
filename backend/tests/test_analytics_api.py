"""M5 endpoints through FastAPI (§5, §11): progress, bias, distribution, roster,
unit browser + detail, reprioritize — plus the role gating that protects them and
a wizard-shaped end-to-end (clone → project → bulk upload → label → progress).

Labeling is driven with the admin token, which ``_authorize_annotator`` lets act
as any annotator id — so one client can play the whole team without juggling keys.
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
REVIEWER_KEY = "reviewer-key"
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
    seeder.add(User(email="rev@x.com", role="reviewer", api_key_hash=hash_api_key(REVIEWER_KEY)))
    worker = User(email="worker@x.com", role="annotator", api_key_hash=hash_api_key(ANNOTATOR_KEY))
    seeder.add(worker)
    seeder.flush()
    seeder.add_all(
        [
            Annotator(kind="human", user_id=worker.id, display_name="w1"),
            Annotator(kind="human", user_id=worker.id, display_name="w2"),
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


def _template_id(engine, name):
    with Session(bind=engine) as s:
        return s.scalar(select(Template.id).where(Template.name == name))


def _annotator_ids(engine):
    with Session(bind=engine) as s:
        return list(s.scalars(select(Annotator.id).order_by(Annotator.id)))


def _create_project(client, engine, template="image-classification", **kw):
    body = {
        "name": kw.pop("name", "p"),
        "template_id": _template_id(engine, template),
        "labels_per_unit": 2,
        "gold_ratio": 0.0,
        **kw,
    }
    r = client.post("/projects", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _bulk(client, project_id, rows, **kw):
    jsonl = "\n".join(json.dumps(r) for r in rows)
    r = client.post(f"/projects/{project_id}/units:bulk", json={"jsonl": jsonl, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _label(client, project_id, annotator_ids, raw, cap=100):
    """Drive labeling as the admin (acts as any annotator)."""
    filled = 0
    i = 0
    while filled < cap:
        aid = annotator_ids[i % len(annotator_ids)]
        nxt = client.get(f"/tasks/next?annotator={aid}&project={project_id}")
        if nxt.status_code == 204:
            i += 1
            if i > cap * 2:
                break
            continue
        slot = nxt.json()
        sub = client.post(f"/tasks/{slot['slot_id']}/submit?annotator={aid}", json={"raw": raw})
        assert sub.status_code in (200, 201), sub.text
        filled += 1
        i += 1
    return filled


# --- project list + wizard-shaped end-to-end --------------------------------


def test_wizard_end_to_end_from_jsonl_fixture(client, engine):
    """Clone a gallery template, create a project on it, bulk-upload a JSONL
    fixture (per-row report), label, and see progress move — the M5 acceptance
    'wizard creates a working project end-to-end from a JSONL fixture'."""
    # Step 1: clone a gallery template into an editable draft.
    src = _template_id(engine, "image-classification")
    cloned = client.post(f"/templates/{src}:clone", json={"new_name": "my-classes"})
    assert cloned.status_code == 201, cloned.text
    tmpl_id = cloned.json()["id"]

    # Step 2: create the project on the clone.
    r = client.post(
        "/projects",
        json={"name": "wiz", "template_id": tmpl_id, "labels_per_unit": 2, "gold_ratio": 0.0},
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    # Step 3: bulk upload with one malformed row → per-row validation report.
    report = _bulk(
        client,
        pid,
        [
            {"payload": {"image_url": "http://x/1.png"}},
            {"payload": {"image_url": "http://x/2.png"}, "priority": 5},
            {"not_payload": True},  # rejected
        ],
        batch_name="first-drop",
    )
    assert report["unit_count"] == 2
    assert report["rejected_count"] == 1
    assert len(report["rejected_rows"]) == 1

    # Project shows up in the list.
    listing = client.get("/projects").json()
    assert pid in [p["id"] for p in listing]

    # Step 4: label and confirm progress reflects it.
    ids = _annotator_ids(engine)
    _label(client, pid, ids, {"category": "cat"})
    prog = client.get(f"/projects/{pid}/progress").json()
    assert prog["funnel"]["total"] == 2
    assert prog["labels_total"] == prog["slots"]["filled"]
    assert prog["labels_total"] > 0


# --- unit browser: filters compose + detail drawer --------------------------


def test_unit_filters_compose(client, engine):
    pid = _create_project(client, engine, name="filt")
    _bulk(
        client,
        pid,
        [
            {"payload": {"image_url": "http://x/1.png"}, "priority": 9},
            {"payload": {"image_url": "http://x/2.png"}, "priority": 1},
            {
                "payload": {"image_url": "http://x/3.png"},
                "is_gold": True,
                "gold_expected": {"category": "cat"},
            },
        ],
    )
    # is_gold filter.
    golds = client.get(f"/projects/{pid}/units?is_gold=true").json()
    assert len(golds) == 1 and golds[0]["is_gold"] is True
    # min_priority composes with status.
    hi = client.get(f"/projects/{pid}/units?min_priority=5&status=pending").json()
    assert len(hi) == 1 and hi[0]["priority"] == 9
    # escalated=true → none yet.
    assert client.get(f"/projects/{pid}/units?escalated=true").json() == []
    # Ordered by priority desc.
    ordered = [u["priority"] for u in client.get(f"/projects/{pid}/units").json()]
    assert ordered == sorted(ordered, reverse=True)


def test_unit_detail_drawer(client, engine):
    pid = _create_project(client, engine, name="drawer")
    _bulk(client, pid, [{"payload": {"image_url": "http://x/1.png"}}])
    ids = _annotator_ids(engine)
    _label(client, pid, ids, {"category": "dog"})

    units = client.get(f"/projects/{pid}/units").json()
    detail = client.get(f"/units/{units[0]['id']}").json()
    assert detail["payload"] == {"image_url": "http://x/1.png"}
    assert len(detail["labels"]) == 2
    row = detail["labels"][0]
    assert row["annotator_kind"] == "human"
    assert "reputation" in row and "value" in row
    assert detail["consensus"]["keys"]["category"]["winner"] == "dog"


def test_unit_detail_404(client):
    assert client.get("/units/987654").status_code == 404


# --- reprioritize -----------------------------------------------------------


def test_reprioritize_by_batch(client, engine):
    pid = _create_project(client, engine, name="reprio")
    report = _bulk(
        client,
        pid,
        [{"payload": {"image_url": f"http://x/{i}.png"}} for i in range(3)],
        batch_name="b1",
    )
    batches = client.get(f"/projects/{pid}/batches").json()
    assert len(batches) == 1
    bid = batches[0]["id"]

    r = client.post(f"/projects/{pid}/units:reprioritize", json={"priority": 50, "batch_id": bid})
    assert r.status_code == 200
    assert r.json()["updated"] == 3
    prios = {u["priority"] for u in client.get(f"/projects/{pid}/units").json()}
    assert prios == {50}
    assert report["unit_count"] == 3  # sanity


# --- distribution + roster --------------------------------------------------


def test_distribution_splits_by_kind(client, engine):
    pid = _create_project(client, engine, name="dist")
    _bulk(client, pid, [{"payload": {"image_url": f"http://x/{i}.png"}} for i in range(2)])
    ids = _annotator_ids(engine)
    _label(client, pid, ids, {"category": "cat"})

    dist = client.get(f"/projects/{pid}/analytics/distribution").json()
    cat = dist["keys"]["category"]
    assert cat["total"] == cat["overall"]["cat"]
    assert "human" in cat["by_kind"]


def test_roster_lists_annotators_with_reputation(client, engine):
    pid = _create_project(client, engine, name="roster")
    _bulk(client, pid, [{"payload": {"image_url": f"http://x/{i}.png"}} for i in range(2)])
    ids = _annotator_ids(engine)
    _label(client, pid, ids, {"category": "cat"})

    roster = client.get(f"/projects/{pid}/annotators").json()
    assert roster["count"] == 2
    row = roster["annotators"][0]
    assert row["kind"] == "human"
    assert row["labels_valid"] >= 1
    assert "reputation" in row


# --- role gating ------------------------------------------------------------


def test_analytics_require_reviewer(client, engine):
    """Annotator token is forbidden on reviewer-gated analytics; §5 auth.

    ``/progress``, ``/analytics/bias`` and ``/analytics/distribution`` and the
    roster expose peers' votes and cross-annotator numbers, so they sit behind the
    reviewer gate — while the unit *list* stays annotator-readable."""
    pid = _create_project(client, engine, name="gate")
    worker = {"Authorization": f"Bearer {ANNOTATOR_KEY}"}

    for path in (
        f"/projects/{pid}/progress",
        f"/projects/{pid}/analytics/bias",
        f"/projects/{pid}/analytics/distribution",
        f"/projects/{pid}/annotators",
    ):
        r = client.get(path, headers=worker)
        assert r.status_code == 403, f"{path} should be reviewer-gated, got {r.status_code}"

    # A reviewer token passes.
    rev = {"Authorization": f"Bearer {REVIEWER_KEY}"}
    assert client.get(f"/projects/{pid}/progress", headers=rev).status_code == 200
    # The unit list is fine for an annotator.
    assert client.get(f"/projects/{pid}/units", headers=worker).status_code == 200


def test_bias_and_progress_404_for_unknown_project(client):
    assert client.get("/projects/424242/progress").status_code == 404
    assert client.get("/projects/424242/analytics/bias").status_code == 404


# --- annotator landing page (§11, M5) ---------------------------------------


def test_available_work_lists_projects_with_open_labels(client, engine):
    """The landing endpoint reports remaining labels per project, most first."""
    p1 = _create_project(client, engine, name="land1", labels_per_unit=2)
    _bulk(client, p1, [{"payload": {"image_url": f"http://x/{i}.png"}} for i in range(3)])  # 6
    p2 = _create_project(client, engine, name="land2", labels_per_unit=1)
    _bulk(client, p2, [{"payload": {"image_url": "http://x/z.png"}}])  # 1

    a1 = _annotator_ids(engine)[0]
    body = client.get(f"/tasks/available?annotator={a1}").json()
    assert body["annotator_id"] == a1
    rows = {r["project_id"]: r for r in body["projects"]}
    assert rows[p1]["available_labels"] == 6
    assert rows[p2]["available_labels"] == 1
    # Most work first.
    ordered = [r["project_id"] for r in body["projects"] if r["available_labels"] > 0]
    assert ordered[:2] == [p1, p2]


def test_available_work_authorizes_like_other_task_calls(client, engine):
    """A worker may list their own work; the admin may list anyone's (§5 auth)."""
    _create_project(client, engine, name="auth")
    a1 = _annotator_ids(engine)[0]  # owned by the worker user
    worker = {"Authorization": f"Bearer {ANNOTATOR_KEY}"}
    assert client.get(f"/tasks/available?annotator={a1}", headers=worker).status_code == 200
    # Admin (default client headers) can list it too.
    assert client.get(f"/tasks/available?annotator={a1}").status_code == 200
