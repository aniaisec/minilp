"""Template sample payloads — gallery preview + wizard prefill (§11, M5).

Covers the pure field/sample generation and the GET/PUT endpoints, including the
required-field check that stops a sample missing a mandatory payload key, and the
rule that a builtin can carry a saved sample even though its schema is immutable.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import Template, User
from app.services.auth.roles import hash_api_key
from app.services.templates.sample import payload_fields, sample_payload
from app.services.templates.seed import seed_templates

ADMIN_KEY = "admin-key"
WORKER_KEY = "worker-key"


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
    seeder.add(User(email="a@x.com", role="admin", api_key_hash=hash_api_key(ADMIN_KEY)))
    seeder.add(User(email="w@x.com", role="annotator", api_key_hash=hash_api_key(WORKER_KEY)))
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


def _tid(engine, name):
    with Session(bind=engine) as s:
        return s.scalar(select(Template.id).where(Template.name == name))


# --- pure generation --------------------------------------------------------


IMAGE_SCHEMA = {
    "name": "img",
    "inputs": [{"id": "c", "type": "radio", "options": ["a"], "required": True}],
    "display": [
        {"type": "image", "source": "$unit.image_url"},
        {"type": "text", "source": "$unit.context", "optional": True},
    ],
}


def test_payload_fields_split_required_and_optional():
    fields = payload_fields(IMAGE_SCHEMA)
    assert fields["required"] == ["image_url"]
    assert fields["optional"] == ["context"]


def test_sample_payload_types_by_block():
    sample = sample_payload(IMAGE_SCHEMA)
    assert set(sample) == {"image_url", "context"}
    assert sample["image_url"].startswith("https://")  # image → URL


# --- endpoints --------------------------------------------------------------


def test_get_sample_generates_when_none_saved(client, engine):
    tid = _tid(engine, "image-classification")
    body = client.get(f"/templates/{tid}/sample").json()
    assert body["saved"] is False
    assert "image_url" in body["sample"]
    assert body["fields"]["required"] == ["image_url"]


def test_put_sample_saves_and_get_returns_it_even_on_builtin(client, engine):
    tid = _tid(engine, "image-classification")
    custom = {"image_url": "http://x/kitten.png", "context": "a kitten"}
    put = client.put(f"/templates/{tid}/sample", json={"sample": custom})
    assert put.status_code == 200, put.text
    assert put.json()["saved"] is True

    got = client.get(f"/templates/{tid}/sample").json()
    assert got["saved"] is True
    assert got["sample"] == custom
    # Saving a sample must NOT bump the immutable schema version.
    tmpl = client.get(f"/templates/{tid}").json()
    assert tmpl["version"] == 1
    assert tmpl["sample"] == custom


def test_put_sample_rejects_missing_required_field(client, engine):
    tid = _tid(engine, "image-classification")
    r = client.put(f"/templates/{tid}/sample", json={"sample": {"context": "no image"}})
    assert r.status_code == 422
    assert any("image_url" in e for e in r.json()["detail"]["errors"])


def test_put_sample_is_admin_only(client, engine):
    tid = _tid(engine, "image-classification")
    r = client.put(
        f"/templates/{tid}/sample",
        json={"sample": {"image_url": "http://x/1.png"}},
        headers={"Authorization": f"Bearer {WORKER_KEY}"},
    )
    assert r.status_code == 403


def test_sample_404_for_unknown_template(client):
    assert client.get("/templates/99999/sample").status_code == 404
