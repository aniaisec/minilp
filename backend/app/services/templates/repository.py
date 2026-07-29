"""DB-facing template operations: create, clone, edit-with-versioning (§2.5).

Built-ins are immutable — cloning is how you "edit" one. A schema-affecting edit to
a custom template creates a new row with an incremented version; a presentation-only
edit updates in place (§12 invariant 3).
"""

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, Template
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


# --- deletion ---------------------------------------------------------------


class TemplateInUseError(TemplateError):
    """A template version still backs one or more projects.

    Carries the blockers so the API can name them. "Template 7 is in use" sends
    someone hunting through the project list; "in use by 'Q3 preference run'
    (#4)" does not.
    """

    def __init__(self, message: str, blockers: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.blockers = blockers


def template_usage(db: Session, template_ids: list[int]) -> list[dict[str, Any]]:
    """Projects bound to any of these template rows, newest first."""
    if not template_ids:
        return []
    rows = db.execute(
        select(Project.id, Project.name, Project.template_id, Project.template_version)
        .where(Project.template_id.in_(template_ids))
        .order_by(Project.id.desc())
    ).all()
    return [
        {
            "project_id": pid,
            "name": name,
            "template_id": tid,
            "template_version": tversion,
        }
        for pid, name, tid, tversion in rows
    ]


def delete_template(db: Session, template_id: int, *, all_versions: bool = False) -> dict[str, Any]:
    """Delete a custom template version — or its whole lineage (§2.5).

    Three refusals, each for the same underlying reason: **a template is the
    definition of every label collected under it**, so it may only go away when
    nothing depends on it existing.

    - **Builtins are refused.** They are immutable by the same rule that makes
      ``edit_template`` refuse them, they are the M1 acceptance corpus, and the
      seeder would recreate them on the next boot anyway — a delete that
      silently undoes itself is worse than one that says no.
    - **In-use versions are refused**, with the blocking projects named. The FK
      is ``ondelete="RESTRICT"``, so the database would refuse regardless; doing
      the check here turns an IntegrityError into a sentence.
    - **A lineage delete is all-or-nothing.** If any version of the name is in
      use, none are deleted. A partial lineage delete leaves the template's
      history with holes in it and the caller believing it succeeded.

    ``all_versions`` deletes every row sharing the name, which is what "delete
    this template" usually means once a template has been edited a few times.
    """
    target = db.get(Template, template_id)
    if target is None:
        raise TemplateError(f"template {template_id} not found")
    if target.kind == "builtin":
        raise TemplateError(
            f"'{target.name}' is a builtin gallery template and cannot be deleted; "
            "clone it if you want an editable copy"
        )

    if all_versions:
        doomed = list(
            db.scalars(
                select(Template)
                .where(Template.name == target.name, Template.kind != "builtin")
                .order_by(Template.version)
            )
        )
    else:
        doomed = [target]

    blockers = template_usage(db, [t.id for t in doomed])
    if blockers:
        names = ", ".join(f"'{b['name']}' (#{b['project_id']})" for b in blockers[:5])
        more = f" and {len(blockers) - 5} more" if len(blockers) > 5 else ""
        scope = "some version of it is" if all_versions else "it is"
        raise TemplateInUseError(
            f"cannot delete '{target.name}': {scope} in use by {names}{more}. "
            "Delete or rebind those projects first.",
            blockers,
        )

    deleted = [{"id": t.id, "name": t.name, "version": t.version} for t in doomed]
    for tmpl in doomed:
        db.delete(tmpl)
    db.flush()
    return {"deleted": deleted, "count": len(deleted), "name": target.name}


__all__ = [
    "TemplateError",
    "TemplateInUseError",
    "TemplateValidationError",
    "clone_template",
    "create_template",
    "delete_template",
    "edit_template",
    "list_templates",
    "template_usage",
]
