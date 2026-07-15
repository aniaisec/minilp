"""Project creation service (§4, §6.4).

Enforces the §4 CHECK at the application layer: ``labels_per_unit`` must be
divisible by the template's variant-value count (validated against the template).
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models import Project, Template
from app.services.slots.generation import divisibility_ok, n_variant_values


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
