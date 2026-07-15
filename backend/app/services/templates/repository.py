"""DB-facing template operations: create, clone, edit-with-versioning (§2.5).

Built-ins are immutable — cloning is how you "edit" one. A schema-affecting edit to
a custom template creates a new row with an incremented version; a presentation-only
edit updates in place (§12 invariant 3).
"""

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Template
from app.services.templates.validation import TemplateValidationError, validate_template
from app.services.templates.versioning import is_schema_affecting


class TemplateError(ValueError):
    """Non-validation template operation error (e.g. editing a builtin)."""


def create_template(db: Session, schema: dict[str, Any], *, kind: str = "custom") -> Template:
    validate_template(schema)
    schema = copy.deepcopy(schema)
    schema.setdefault("version", 1)
    tmpl = Template(
        name=schema["name"],
        version=schema["version"],
        description=schema.get("description"),
        kind=kind,
        schema=schema,
    )
    db.add(tmpl)
    db.flush()
    return tmpl


def clone_template(db: Session, template_id: int, *, new_name: str | None = None) -> Template:
    """Copy any template into an editable custom draft; the original is untouched."""
    src = db.get(Template, template_id)
    if src is None:
        raise TemplateError(f"template {template_id} not found")

    schema = copy.deepcopy(src.schema)
    name = new_name or f"{src.name} (copy)"
    schema["name"] = name
    schema["version"] = 1
    validate_template(schema)

    draft = Template(
        name=name,
        version=1,
        description=src.description,
        kind="custom",
        schema=schema,
    )
    db.add(draft)
    db.flush()
    return draft


def edit_template(db: Session, template_id: int, new_schema: dict[str, Any]) -> Template:
    """Edit a custom template.

    - Builtins are immutable → ``TemplateError`` (clone instead).
    - Schema-affecting change → new row, version = old + 1.
    - Presentation-only change → update in place.
    """
    current = db.get(Template, template_id)
    if current is None:
        raise TemplateError(f"template {template_id} not found")
    if current.kind == "builtin":
        raise TemplateError("builtin templates are immutable; clone to edit")

    new_schema = copy.deepcopy(new_schema)
    validate_template(new_schema)

    if is_schema_affecting(current.schema, new_schema):
        # Find the highest existing version for this name and bump.
        max_version = db.scalar(
            select(Template.version)
            .where(Template.name == current.name)
            .order_by(Template.version.desc())
            .limit(1)
        )
        new_version = (max_version or current.version) + 1
        new_schema["name"] = current.name
        new_schema["version"] = new_version
        bumped = Template(
            name=current.name,
            version=new_version,
            description=new_schema.get("description", current.description),
            kind="custom",
            schema=new_schema,
        )
        db.add(bumped)
        db.flush()
        return bumped

    # Presentation-only: mutate in place, keep the same version.
    new_schema["name"] = current.name
    new_schema["version"] = current.version
    current.schema = new_schema
    current.description = new_schema.get("description", current.description)
    db.add(current)
    db.flush()
    return current


def list_templates(db: Session) -> list[Template]:
    return list(db.scalars(select(Template).order_by(Template.name, Template.version)))


__all__ = [
    "TemplateError",
    "TemplateValidationError",
    "clone_template",
    "create_template",
    "edit_template",
    "list_templates",
]
