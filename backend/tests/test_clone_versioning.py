"""Clone + versioning against the DB (§2.5, M1 acceptance)."""

import copy

import pytest
from sqlalchemy import select

from app.models import Template
from app.services.templates.repository import (
    TemplateError,
    clone_template,
    edit_template,
)
from app.services.templates.seed import seed_templates


def _seed_one(db) -> Template:
    seed_templates(db)
    return db.scalar(select(Template).where(Template.name == "image-classification"))


def test_clone_of_builtin_is_editable_original_untouched(db) -> None:
    builtin = _seed_one(db)
    original_schema = copy.deepcopy(builtin.schema)

    draft = clone_template(db, builtin.id)
    assert draft.id != builtin.id
    assert draft.kind == "custom"

    # editing the clone (presentation-only) succeeds
    new_schema = copy.deepcopy(draft.schema)
    new_schema["layout"] = {"arrangement": "stack", "width": "lg"}
    edited = edit_template(db, draft.id, new_schema)
    assert edited.id == draft.id  # in place

    # original builtin is unchanged
    db.refresh(builtin)
    assert builtin.schema == original_schema
    assert builtin.kind == "builtin"


def test_builtin_is_immutable(db) -> None:
    builtin = _seed_one(db)
    schema = copy.deepcopy(builtin.schema)
    schema["layout"] = {"arrangement": "stack"}
    with pytest.raises(TemplateError):
        edit_template(db, builtin.id, schema)


def test_layout_edit_does_not_bump_version(db) -> None:
    builtin = _seed_one(db)
    draft = clone_template(db, builtin.id)
    v0 = draft.version

    schema = copy.deepcopy(draft.schema)
    schema["layout"] = {"arrangement": "split", "ratio": [3, 2]}
    edited = edit_template(db, draft.id, schema)
    assert edited.id == draft.id
    assert edited.version == v0


def test_schema_edit_bumps_version_new_row(db) -> None:
    builtin = _seed_one(db)
    draft = clone_template(db, builtin.id)
    v0 = draft.version

    schema = copy.deepcopy(draft.schema)
    schema["inputs"][0]["options"] = ["cat", "dog", "bird", "fish"]
    bumped = edit_template(db, draft.id, schema)

    assert bumped.id != draft.id  # new row
    assert bumped.version == v0 + 1
    assert bumped.name == draft.name

    # old version still exists unchanged
    db.refresh(draft)
    assert draft.version == v0
    assert draft.schema["inputs"][0]["options"] == ["cat", "dog", "bird"]
