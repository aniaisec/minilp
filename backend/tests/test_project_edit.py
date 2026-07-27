"""M6 — editing a live project (§2.5 "one editor, three entry points").

The editor that creates and edits a template also edits a project after it was
created. Two of those edits are more than a column write and are pinned here:

- **K changes reshape the slot pool** in whole balanced rounds (§2.7), and refuse
  to shrink past work already collected.
- **A template-schema change clones-and-rebinds** rather than mutating a version
  another project may share.
"""

import json

import pytest
from sqlalchemy import select

from app.models import Annotator, Label, Slot, Template, Unit, User
from app.services.assignment import next_task, submit_label
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import ProjectError, create_project, update_project
from app.services.slots.generation import verify_balance
from app.services.templates.seed import seed_templates
from app.services.templates.validation import TemplateValidationError

# --- helpers ----------------------------------------------------------------


def _annotator(db, email: str) -> Annotator:
    user = User(email=email, role="annotator")
    db.add(user)
    db.flush()
    ann = Annotator(kind="human", user_id=user.id, display_name=email)
    db.add(ann)
    db.flush()
    return ann


def _project(db, name, *, template="image-classification", **kwargs):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == template))
    return create_project(db, name=name, template_id=tmpl.id, **kwargs)


def _ingest(db, project, n=3, payload=None):
    payload = payload or {"image_url": "http://x/1.png"}
    lines = "\n".join(json.dumps({"payload": payload}) for _ in range(n))
    return ingest_units(db, project, parse_jsonl(lines))


def _slots(db, unit_id):
    return list(db.scalars(select(Slot).where(Slot.unit_id == unit_id)))


# --- plain config edits -----------------------------------------------------


def test_guidelines_and_thresholds_edit_in_place(db) -> None:
    project = _project(db, "p", labels_per_unit=1, guidelines_md="old")
    updated, report = update_project(
        db,
        project.id,
        guidelines_md="# New rules",
        gold_ratio=0.25,
        min_reputation=0.6,
        agreement={"category": {"match": "exact", "min_consensus": 0.9}},
    )
    assert updated.guidelines_md == "# New rules"
    assert updated.gold_ratio == 0.25
    assert updated.min_reputation == 0.6
    assert updated.agreement["category"]["min_consensus"] == 0.9
    # No template churn and no slot churn for a config-only edit.
    assert report == {"rebound": False, "slots_changed": 0}
    assert updated.template_id == project.template_id


def test_an_out_of_range_gold_ratio_is_rejected(db) -> None:
    project = _project(db, "p", labels_per_unit=1)
    with pytest.raises(ProjectError, match="gold_ratio"):
        update_project(db, project.id, gold_ratio=1.5)


# --- changing K reshapes slots ---------------------------------------------


def test_raising_k_opens_more_slots_on_every_unit(db) -> None:
    project = _project(db, "p", labels_per_unit=1, max_labels_per_unit=4)
    result = _ingest(db, project, n=3)
    units = list(db.scalars(select(Unit).where(Unit.project_id == project.id)))
    assert all(len(_slots(db, u.id)) == 1 for u in units)

    _, report = update_project(db, project.id, labels_per_unit=3)
    assert report["slots_changed"] == 6  # 3 units × 2 new slots
    for unit in units:
        assert len(_slots(db, unit.id)) == 3
    assert result.unit_count == 3


def test_raising_k_on_a_variant_template_keeps_the_balance_invariant(db) -> None:
    """§2.7: growth adds whole rounds, so K/n per variant value still holds."""
    project = _project(
        db,
        "sbs",
        template="side-by-side-preference",
        labels_per_unit=2,
        max_labels_per_unit=4,
    )
    _ingest(db, project, n=2, payload={"prompt": "p", "response_a": "a", "response_b": "b"})
    tmpl = db.get(Template, project.template_id)

    update_project(db, project.id, labels_per_unit=4)
    for unit in db.scalars(select(Unit).where(Unit.project_id == project.id)):
        variants = [s.variant for s in _slots(db, unit.id)]
        assert len(variants) == 4
        assert verify_balance(variants, tmpl.schema)


def test_k_must_stay_divisible_by_the_variant_count(db) -> None:
    project = _project(
        db, "sbs", template="side-by-side-preference", labels_per_unit=2, max_labels_per_unit=4
    )
    _ingest(db, project, n=1, payload={"prompt": "p", "response_a": "a", "response_b": "b"})
    with pytest.raises(ProjectError, match="divisible"):
        update_project(db, project.id, labels_per_unit=3)


def test_lowering_k_removes_open_slots(db) -> None:
    project = _project(db, "p", labels_per_unit=3, max_labels_per_unit=3)
    _ingest(db, project, n=2)
    _, report = update_project(db, project.id, labels_per_unit=1)
    assert report["slots_changed"] == 4  # 2 units × 2 removed
    for unit in db.scalars(select(Unit).where(Unit.project_id == project.id)):
        assert len(_slots(db, unit.id)) == 1


def test_lowering_k_below_collected_work_is_refused(db) -> None:
    """Retracting a slot someone already labeled would either destroy a label or
    break balance — the editor says no instead of silently doing either."""
    project = _project(db, "p", labels_per_unit=2, max_labels_per_unit=2)
    _ingest(db, project, n=1)
    a, b = _annotator(db, "a@x"), _annotator(db, "b@x")
    for ann in (a, b):
        slot = next_task(db, ann.id, project.id)
        submit_label(db, slot.id, ann.id, raw={"category": "cat"})

    with pytest.raises(ProjectError, match="already has"):
        update_project(db, project.id, labels_per_unit=1)
    # Nothing was lost.
    assert db.scalar(select(Label).where(Label.annotator_id == a.id)) is not None


# --- clone-and-rebind (§2.5) ------------------------------------------------


def _edited_schema(schema: dict) -> dict:
    """A schema-affecting change: one extra required input."""
    new = json.loads(json.dumps(schema))
    new["inputs"].append({"id": "notes", "type": "free_text", "label": "Notes"})
    return new


def test_a_schema_change_clones_and_rebinds_leaving_the_original_alone(db) -> None:
    project = _project(db, "p", labels_per_unit=1)
    original = db.get(Template, project.template_id)
    original_inputs = len(original.schema["inputs"])

    updated, report = update_project(
        db, project.id, template_schema=_edited_schema(original.schema)
    )

    assert report["rebound"] is True
    assert updated.template_id != original.id
    rebound = db.get(Template, updated.template_id)
    assert len(rebound.schema["inputs"]) == original_inputs + 1
    assert rebound.kind == "custom"
    # The gallery original is untouched — other projects still see what they saw.
    db.refresh(original)
    assert len(original.schema["inputs"]) == original_inputs
    assert updated.template_version == rebound.version


def test_an_identical_schema_does_not_rebind(db) -> None:
    """Opening the editor and saving without touching anything is a no-op."""
    project = _project(db, "p", labels_per_unit=1)
    original = db.get(Template, project.template_id)
    updated, report = update_project(db, project.id, template_schema=original.schema)
    assert report["rebound"] is False
    assert updated.template_id == original.id


def test_an_invalid_schema_is_rejected_before_anything_is_written(db) -> None:
    project = _project(db, "p", labels_per_unit=1, guidelines_md="keep me")
    broken = _edited_schema(db.get(Template, project.template_id).schema)
    broken["inputs"].append({"id": "dupe", "type": "select", "options": ["only-one"]})

    with pytest.raises(TemplateValidationError):
        update_project(db, project.id, template_schema=broken, guidelines_md="clobbered")

    # The schema is validated before anything else is touched, so the rest of the
    # edit didn't half-apply: no rebind, and the guidelines are as they were.
    assert project.guidelines_md == "keep me"
    assert project.template_id == db.get(Template, project.template_id).id


def test_rebinding_can_use_the_new_palette(db) -> None:
    """A project retyped in the builder to use an M6 field validates and rebinds."""
    project = _project(db, "p", labels_per_unit=1)
    schema = json.loads(json.dumps(db.get(Template, project.template_id).schema))
    schema["inputs"].append(
        {"id": "severity", "type": "slider", "label": "Severity", "min": 0, "max": 10, "step": 1}
    )
    updated, report = update_project(db, project.id, template_schema=schema)
    assert report["rebound"] is True
    rebound = db.get(Template, updated.template_id)
    assert rebound.schema["inputs"][-1]["type"] == "slider"
