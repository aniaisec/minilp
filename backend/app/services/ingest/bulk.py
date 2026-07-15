"""Bulk unit ingest (§5 ``POST /projects/{id}/units:bulk``, M1).

Accepts parsed JSONL rows, validates each unit payload against the project's
template, creates a batch, ingests valid rows (with slot pre-generation), and
returns a per-row validation report — valid rows land, malformed rows are rejected
with their 1-based row number and reason.
"""

import json
import random
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models import Batch, Project, Slot, Template, Unit
from app.services.slots.generation import plan_slot_variants
from app.services.templates.preview import validate_payload


@dataclass
class RowResult:
    row: int  # 1-based line number in the upload
    ok: bool
    unit_id: int | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class IngestResult:
    batch_id: int
    unit_count: int
    rejected_count: int
    rows: list[RowResult]

    def as_report(self) -> dict[str, Any]:
        return ingest_report(self)


def ingest_report(result: IngestResult) -> dict[str, Any]:
    return {
        "batch_id": result.batch_id,
        "unit_count": result.unit_count,
        "rejected_count": result.rejected_count,
        "rejected_rows": [{"row": r.row, "errors": r.errors} for r in result.rows if not r.ok],
        "accepted_rows": [{"row": r.row, "unit_id": r.unit_id} for r in result.rows if r.ok],
    }


def parse_jsonl(text: str) -> list[tuple[int, dict[str, Any] | None, str | None]]:
    """Parse JSONL into (row_number, obj|None, error|None). Blank lines skipped."""
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                out.append((i, None, "row is not a JSON object"))
            else:
                out.append((i, obj, None))
        except json.JSONDecodeError as e:
            out.append((i, None, f"invalid JSON: {e.msg}"))
    return out


def ingest_units(
    db: Session,
    project: Project,
    rows: list[tuple[int, dict[str, Any] | None, str | None]],
    *,
    batch_name: str | None = None,
    source_filename: str | None = None,
    rng: random.Random | None = None,
) -> IngestResult:
    """Ingest parsed rows for a project, generating balanced slots per valid unit."""
    template = db.get(Template, project.template_id)
    if template is None:
        raise ValueError(f"project {project.id} references missing template")
    schema = template.schema

    batch = Batch(
        project_id=project.id,
        name=batch_name,
        source_filename=source_filename,
        unit_count=0,
        rejected_count=0,
    )
    db.add(batch)
    db.flush()  # assign batch.id

    results: list[RowResult] = []
    accepted = 0
    rejected = 0

    for row_no, obj, parse_err in rows:
        if parse_err is not None:
            results.append(RowResult(row=row_no, ok=False, errors=[parse_err]))
            rejected += 1
            continue

        payload = obj.get("payload", obj) if "payload" in obj else obj
        problems = validate_payload(schema, payload)

        # Optional per-row fields
        is_gold = bool(obj.get("is_gold", False))
        gold_expected = obj.get("gold_expected")
        priority = obj.get("priority", 0)
        if not isinstance(priority, int):
            problems.append("priority must be an integer")
        if is_gold and gold_expected is None:
            problems.append("gold unit missing gold_expected")

        if problems:
            results.append(RowResult(row=row_no, ok=False, errors=problems))
            rejected += 1
            continue

        unit = Unit(
            project_id=project.id,
            batch_id=batch.id,
            payload=payload,
            priority=priority,
            is_gold=is_gold,
            gold_expected=gold_expected,
            status="pending",
        )
        db.add(unit)
        db.flush()  # assign unit.id

        variants = plan_slot_variants(schema, project.labels_per_unit, rng=rng)
        for variant in variants:
            db.add(Slot(unit_id=unit.id, variant=variant, status="open"))

        results.append(RowResult(row=row_no, ok=True, unit_id=unit.id))
        accepted += 1

    batch.unit_count = accepted
    batch.rejected_count = rejected
    db.flush()

    return IngestResult(
        batch_id=batch.id,
        unit_count=accepted,
        rejected_count=rejected,
        rows=results,
    )
