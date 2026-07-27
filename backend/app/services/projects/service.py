"""Project creation and configuration editing (§4, §2.5, §6.4).

Enforces the §4 CHECK at the application layer: ``labels_per_unit`` must be
divisible by the template's variant-value count (validated against the template).

``update_project`` is the third entry point of the "one editor" rule (§2.5): the
same editor that creates and edits a template also edits a live project's config.
Two operations there are more than a column write and live here rather than in the
API layer:

- **Changing K** re-shapes the slot pool. Growing K opens another *balanced* round
  of slots on every unfinished unit (§2.7 — never a partial round, so K/n still
  holds at completion). Shrinking K is only allowed where the extra slots are
  still open, because retracting a slot someone already labeled would either
  destroy a label or break the balance invariant.
- **Changing the template schema** clones-and-rebinds rather than mutating a
  version other projects may share (§2.5). Already-collected labels keep pointing
  at the version they were collected under.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Project, Slot, Template, Unit
from app.services.slots.generation import (
    divisibility_ok,
    n_variant_values,
    plan_slot_variants,
)
from app.services.templates.repository import clone_template
from app.services.templates.validation import validate_template


class ProjectError(ValueError):
    """Invalid project configuration."""


def create_project(
    db: Session,
    *,
    name: str,
    template_id: int,
    labels_per_unit: int = 1,
    max_labels_per_unit: int | None = None,
    guidelines_md: str | None = None,
    agreement: dict[str, Any] | None = None,
    gold_ratio: float = 0.1,
    lease_minutes: int = 30,
    min_reputation: float = 0.0,
    pipeline: list[dict[str, Any]] | None = None,
    description: str | None = None,
    config: dict[str, Any] | None = None,
) -> Project:
    template = db.get(Template, template_id)
    if template is None:
        raise ProjectError(f"template {template_id} not found")

    if labels_per_unit < 1:
        raise ProjectError("labels_per_unit must be >= 1")

    if not divisibility_ok(template.schema, labels_per_unit):
        n = n_variant_values(template.schema)
        raise ProjectError(
            f"labels_per_unit={labels_per_unit} must be divisible by "
            f"{n} variant values for template '{template.name}'"
        )

    max_lpu = max_labels_per_unit if max_labels_per_unit is not None else labels_per_unit
    if max_lpu < labels_per_unit:
        raise ProjectError("max_labels_per_unit must be >= labels_per_unit")
    if max_lpu % n_variant_values(template.schema) != 0:
        raise ProjectError("max_labels_per_unit must also satisfy variant divisibility")

    project = Project(
        name=name,
        description=description,
        template_id=template.id,
        template_version=template.version,
        guidelines_md=guidelines_md,
        labels_per_unit=labels_per_unit,
        max_labels_per_unit=max_lpu,
        agreement=agreement,
        gold_ratio=gold_ratio,
        lease_minutes=lease_minutes,
        min_reputation=min_reputation,
        pipeline=pipeline,
        config=config,
    )
    db.add(project)
    db.flush()
    return project


# --- M6: edit a live project (§2.5 "one editor, three entry points") ---------

# Config fields the project editor may set directly. ``template_id`` and
# ``labels_per_unit`` are handled separately because they re-shape slots.
PLAIN_FIELDS = (
    "name",
    "description",
    "guidelines_md",
    "agreement",
    "gold_ratio",
    "lease_minutes",
    "min_reputation",
    "pipeline",
    "config",
)


def _open_slot_ids(db: Session, unit_id: int) -> list[int]:
    return list(db.scalars(select(Slot.id).where(Slot.unit_id == unit_id, Slot.status == "open")))


def _active_slot_count(db: Session, unit_id: int) -> int:
    """Slots still counting toward overlap — voided ones have been retired."""
    return (
        db.scalar(
            select(func.count(Slot.id)).where(Slot.unit_id == unit_id, Slot.status != "voided")
        )
        or 0
    )


def _reshape_overlap(db: Session, project: Project, new_k: int, schema: dict[str, Any]) -> int:
    """Grow or shrink every unit's slot pool to ``new_k``. Returns slots changed.

    Growth adds a whole balanced round per unit (§2.7). Shrinking removes only
    *open* slots, and refuses if a unit has already been labeled past the new K —
    the alternative would be silently discarding collected work.
    """
    units = list(db.scalars(select(Unit).where(Unit.project_id == project.id)))
    delta_total = 0

    if new_k > project.labels_per_unit:
        for unit in units:
            if unit.status == "finalized":
                continue
            missing = new_k - _active_slot_count(db, unit.id)
            if missing <= 0:
                continue
            for variant in plan_slot_variants(schema, missing):
                db.add(Slot(unit_id=unit.id, variant=variant, status="open"))
                delta_total += 1
    elif new_k < project.labels_per_unit:
        for unit in units:
            excess = _active_slot_count(db, unit.id) - new_k
            if excess <= 0:
                continue
            open_ids = _open_slot_ids(db, unit.id)
            if len(open_ids) < excess:
                raise ProjectError(
                    f"cannot lower labels_per_unit to {new_k}: unit {unit.id} already has "
                    f"{_active_slot_count(db, unit.id) - len(open_ids)} labeled or leased "
                    "slots. Lower it before collection starts, or leave K as it is."
                )
            for slot_id in open_ids[:excess]:
                db.delete(db.get(Slot, slot_id))
                delta_total += 1

    db.flush()
    return delta_total


def update_project(
    db: Session,
    project_id: int,
    *,
    template_schema: dict[str, Any] | None = None,
    labels_per_unit: int | None = None,
    max_labels_per_unit: int | None = None,
    **fields: Any,
) -> tuple[Project, dict[str, Any]]:
    """Edit a live project's configuration; returns ``(project, change report)``.

    ``template_schema``, when it differs from the bound template's, clones the
    template into a new custom version and rebinds the project to it (§2.5) — the
    original is left untouched for whoever else is using it.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectError(f"project {project_id} not found")
    template = db.get(Template, project.template_id)
    if template is None:
        raise ProjectError(f"project {project_id} references missing template")

    report: dict[str, Any] = {"rebound": False, "slots_changed": 0}

    # 1. Template schema — validate, then clone-and-rebind if it actually changed.
    schema = template.schema
    if template_schema is not None and template_schema != template.schema:
        validate_template(template_schema)
        rebound = clone_template(db, template.id, new_name=f"{project.name} template")
        rebound.schema = {**template_schema, "name": rebound.name, "version": rebound.version}
        rebound.description = template_schema.get("description", rebound.description)
        validate_template(rebound.schema)
        db.flush()
        project.template_id = rebound.id
        project.template_version = rebound.version
        schema = rebound.schema
        report.update(rebound=True, template_id=rebound.id, template_version=rebound.version)

    # 2. Overlap — divisibility first, then re-shape the slot pool.
    new_k = labels_per_unit if labels_per_unit is not None else project.labels_per_unit
    new_max = (
        max_labels_per_unit if max_labels_per_unit is not None else project.max_labels_per_unit
    )
    if new_k < 1:
        raise ProjectError("labels_per_unit must be >= 1")
    if not divisibility_ok(schema, new_k):
        raise ProjectError(
            f"labels_per_unit={new_k} must be divisible by "
            f"{n_variant_values(schema)} variant values"
        )
    if new_max < new_k:
        raise ProjectError("max_labels_per_unit must be >= labels_per_unit")
    if new_max % n_variant_values(schema) != 0:
        raise ProjectError("max_labels_per_unit must also satisfy variant divisibility")

    if new_k != project.labels_per_unit:
        report["slots_changed"] = _reshape_overlap(db, project, new_k, schema)
    project.labels_per_unit = new_k
    project.max_labels_per_unit = new_max

    # 3. Plain config columns.
    for key, value in fields.items():
        if value is None:
            continue
        if key not in PLAIN_FIELDS:
            raise ProjectError(f"unknown project field '{key}'")
        setattr(project, key, value)

    if not 0.0 <= project.gold_ratio <= 1.0:
        raise ProjectError("gold_ratio must be between 0 and 1")

    db.flush()
    return project, report
