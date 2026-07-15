"""Project divisibility rule + DB-level constraints (§4, §6.4)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import Annotator, Label, Slot, Template, User
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import ProjectError, create_project
from app.services.templates.seed import seed_templates


def _variant_template(db) -> Template:
    seed_templates(db)
    return db.scalar(select(Template).where(Template.name == "side-by-side-preference"))


def test_labels_per_unit_must_divide_variant_count(db) -> None:
    tmpl = _variant_template(db)
    with pytest.raises(ProjectError) as ei:
        create_project(db, name="bad", template_id=tmpl.id, labels_per_unit=3)
    assert "divisible" in str(ei.value)


def test_divisible_k_accepted(db) -> None:
    tmpl = _variant_template(db)
    proj = create_project(db, name="ok", template_id=tmpl.id, labels_per_unit=4)
    assert proj.labels_per_unit == 4


def test_partial_unique_index_blocks_second_valid_label(clean_db) -> None:
    db = clean_db
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == "text-sentiment"))
    proj = create_project(db, name="p", template_id=tmpl.id, labels_per_unit=2)
    result = ingest_units(db, proj, parse_jsonl('{"payload": {"text": "hi"}}'))
    db.flush()
    unit_id = next(r.unit_id for r in result.rows if r.ok)
    slots = db.scalars(select(Slot).where(Slot.unit_id == unit_id)).all()

    user = User(email="a@x.com", role="annotator")
    db.add(user)
    db.flush()
    ann = Annotator(kind="human", user_id=user.id, display_name="A")
    db.add(ann)
    db.flush()

    db.add(
        Label(
            slot_id=slots[0].id,
            unit_id=unit_id,
            annotator_id=ann.id,
            raw={"sentiment": "positive"},
            value={"sentiment": "positive"},
            is_valid=True,
        )
    )
    db.flush()

    # Second *valid* label by the same annotator on the same unit (different slot)
    # must violate the partial unique index.
    db.add(
        Label(
            slot_id=slots[1].id,
            unit_id=unit_id,
            annotator_id=ann.id,
            raw={"sentiment": "negative"},
            value={"sentiment": "negative"},
            is_valid=True,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_annotator_kind_check_constraint(clean_db) -> None:
    db = clean_db
    # human annotator without user_id violates ck_annotators_kind_links
    db.add(Annotator(kind="human", display_name="no-user"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_all_expected_tables_exist(engine) -> None:
    expected = {
        "templates",
        "projects",
        "batches",
        "units",
        "slots",
        "labels",
        "final_labels",
        "users",
        "annotators",
        "judge_configs",
        "reputation_events",
        "webhooks",
    }
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        ).fetchall()
    present = {r[0] for r in rows}
    assert expected <= present
