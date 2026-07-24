"""TSV and JSON-array payload ingest (§11, M5).

The user-facing wizard offers ``.tsv`` and ``.json`` uploads alongside direct
entry; these pin the two new parsers and confirm the required-field check still
fires (a TSV whose header lacks a required column rejects every row with a clear
message) — "verify the required fields are present as expected in the input file".
"""

from sqlalchemy import select

from app.models import Slot, Template, Unit
from app.services.ingest.bulk import (
    ingest_units,
    parse_json_array,
    parse_payload_text,
    parse_tsv,
)
from app.services.projects import create_project
from app.services.templates.seed import seed_templates


def _project(db, template_name, labels_per_unit=1):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == template_name))
    return create_project(
        db, name=f"p-{template_name}", template_id=tmpl.id, labels_per_unit=labels_per_unit
    )


# --- pure parsers -----------------------------------------------------------


def test_parse_json_array_of_objects():
    rows = parse_json_array('[{"payload": {"image_url": "x"}}, {"payload": {"image_url": "y"}}]')
    assert [r[0] for r in rows] == [1, 2]
    assert all(err is None for _, _, err in rows)


def test_parse_json_array_rejects_non_array_and_non_objects():
    assert parse_json_array('{"payload": {}}')[0][2] == "expected a JSON array of unit objects"
    assert parse_json_array("[1, 2]")[0][2] == "array element is not a JSON object"
    assert parse_json_array("not json")[0][2].startswith("invalid JSON")


def test_parse_tsv_header_maps_columns_to_payload():
    text = "image_url\tcontext\tpriority\nhttp://x/1.png\ta cat\t5\nhttp://x/2.png\t\t0"
    rows = parse_tsv(text)
    assert len(rows) == 2
    (_, obj1, err1), (_, obj2, _) = rows
    assert err1 is None
    assert obj1["payload"] == {"image_url": "http://x/1.png", "context": "a cat"}
    assert obj1["priority"] == 5
    # metadata columns don't leak into the payload
    assert "priority" not in obj1["payload"]


def test_parse_tsv_rejects_wrong_column_count_and_bad_types():
    text = "image_url\tpriority\nhttp://x/1.png\tnot-an-int\ntoo\tmany\tcols"
    rows = parse_tsv(text)
    errs = {r[0]: r[2] for r in rows}
    assert "not an integer" in errs[2]
    assert "expected 2 columns, got 3" in errs[3]


def test_parse_tsv_is_gold_and_gold_expected():
    text = 'image_url\tis_gold\tgold_expected\nhttp://x/1.png\ttrue\t{"category": "cat"}'
    (_, obj, err) = parse_tsv(text)[0]
    assert err is None
    assert obj["is_gold"] is True
    assert obj["gold_expected"] == {"category": "cat"}


def test_parse_payload_text_dispatches():
    assert parse_payload_text('{"payload":{}}\n', "jsonl")[0][1] == {"payload": {}}
    assert parse_payload_text('[{"payload":{}}]', "json")[0][1] == {"payload": {}}
    assert parse_payload_text("image_url\nhttp://x/1.png", "tsv")[0][1]["payload"] == {
        "image_url": "http://x/1.png"
    }


# --- ingest integration -----------------------------------------------------


def test_tsv_ingest_creates_units_with_slots(db):
    project = _project(db, "image-classification", labels_per_unit=1)
    text = "image_url\tcontext\nhttp://x/1.png\tone\nhttp://x/2.png\ttwo"
    result = ingest_units(db, project, parse_tsv(text), batch_name="tsv-drop")
    assert result.unit_count == 2
    assert result.rejected_count == 0
    units = db.scalars(select(Unit).where(Unit.project_id == project.id)).all()
    assert {u.payload["image_url"] for u in units} == {"http://x/1.png", "http://x/2.png"}
    slots = db.scalars(
        select(Slot).join(Unit, Slot.unit_id == Unit.id).where(Unit.project_id == project.id)
    ).all()
    assert len(slots) == 2  # K=1 → one slot each


def test_tsv_missing_required_column_rejects_every_row(db):
    """A header without the required 'image_url' column → each row fails clearly."""
    project = _project(db, "image-classification", labels_per_unit=1)
    text = "context\nfirst\nsecond"  # no image_url column at all
    result = ingest_units(db, project, parse_tsv(text))
    assert result.unit_count == 0
    assert result.rejected_count == 2
    for r in result.rows:
        assert any("image_url" in e for e in r.errors)


def test_json_array_ingest(db):
    project = _project(db, "image-classification", labels_per_unit=1)
    rows = parse_json_array('[{"payload": {"image_url": "http://x/1.png"}}]')
    result = ingest_units(db, project, rows)
    assert result.unit_count == 1
