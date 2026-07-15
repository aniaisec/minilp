"""Bulk ingest + slot pre-generation against the DB (§5, §2.7, M1 acceptance)."""

from sqlalchemy import func, select

from app.models import Slot, Template, Unit
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.slots.generation import verify_balance
from app.services.templates.seed import seed_templates


def _project(db, template_name: str, labels_per_unit: int):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == template_name))
    return create_project(
        db,
        name=f"proj-{template_name}",
        template_id=tmpl.id,
        labels_per_unit=labels_per_unit,
    ), tmpl


def test_malformed_rows_rejected_with_row_numbers(db) -> None:
    project, _ = _project(db, "image-classification", 1)
    jsonl = "\n".join(
        [
            '{"payload": {"image_url": "http://x/1.png"}}',  # row 1 ok
            "{not valid json",  # row 2 bad json
            '{"payload": {"context": "no image here"}}',  # row 3 missing required image_url
            '{"payload": {"image_url": "http://x/4.png"}, "priority": 5}',  # row 4 ok
        ]
    )
    rows = parse_jsonl(jsonl)
    result = ingest_units(db, project, rows, batch_name="b1")

    assert result.unit_count == 2
    assert result.rejected_count == 2
    rejected = {r.row for r in result.rows if not r.ok}
    assert rejected == {2, 3}

    report = result.as_report()
    bad_rows = {r["row"] for r in report["rejected_rows"]}
    assert bad_rows == {2, 3}
    # row 3 error names the missing field
    row3 = next(r for r in report["rejected_rows"] if r["row"] == 3)
    assert any("image_url" in e for e in row3["errors"])


def test_valid_rows_get_balanced_slots(db) -> None:
    # side-by-side has 2 variants; K=4 => 2 AB + 2 BA per unit
    project, tmpl = _project(db, "side-by-side-preference", 4)
    jsonl = "\n".join(
        f'{{"payload": {{"prompt": "p{i}", "response_a": "a", "response_b": "b"}}}}'
        for i in range(3)
    )
    rows = parse_jsonl(jsonl)
    result = ingest_units(db, project, rows)
    assert result.unit_count == 3

    units = db.scalars(select(Unit).where(Unit.project_id == project.id)).all()
    assert len(units) == 3
    for unit in units:
        slots = db.scalars(select(Slot).where(Slot.unit_id == unit.id)).all()
        assert len(slots) == 4
        variants = [s.variant for s in slots]
        assert verify_balance(variants, tmpl.schema)
        # exact K/n: 2 per value
        ab = sum(1 for v in variants if v["panel_order"] == "AB")
        ba = sum(1 for v in variants if v["panel_order"] == "BA")
        assert ab == 2 and ba == 2


def test_plain_template_gets_k_null_slots(db) -> None:
    project, _ = _project(db, "text-sentiment", 3)
    rows = parse_jsonl('{"payload": {"text": "I love this"}}')
    result = ingest_units(db, project, rows)
    unit_id = next(r.unit_id for r in result.rows if r.ok)
    slots = db.scalars(select(Slot).where(Slot.unit_id == unit_id)).all()
    assert len(slots) == 3
    assert all(s.variant is None for s in slots)


def test_batch_counts_recorded(db) -> None:
    project, _ = _project(db, "text-sentiment", 1)
    rows = parse_jsonl('{"payload": {"text": "ok"}}\n{"bad json\n{"payload": {"text": "ok2"}}')
    result = ingest_units(db, project, rows, source_filename="upload.jsonl")
    total_slots = db.scalar(
        select(func.count(Slot.id))
        .join(Unit, Unit.id == Slot.unit_id)
        .where(Unit.project_id == project.id)
    )
    assert total_slots == 2  # 2 valid units x K=1
    assert result.unit_count == 2 and result.rejected_count == 1
