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


ParsedRows = list[tuple[int, dict[str, Any] | None, str | None]]

# Columns in a TSV upload that map to unit metadata rather than payload fields.
TSV_RESERVED_COLUMNS = ("priority", "is_gold", "gold_expected")

FORMATS = ("jsonl", "json", "tsv")


def parse_jsonl(text: str) -> ParsedRows:
    """Parse JSONL into (row_number, obj|None, error|None). Blank lines skipped."""
    out: ParsedRows = []
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


def parse_json_array(text: str) -> ParsedRows:
    """Parse a JSON array of unit objects into (row, obj|None, error|None)."""
    stripped = text.strip()
    if not stripped:
        return []
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as e:
        return [(1, None, f"invalid JSON: {e.msg}")]
    if not isinstance(data, list):
        return [(1, None, "expected a JSON array of unit objects")]
    out: ParsedRows = []
    for i, obj in enumerate(data, start=1):
        if isinstance(obj, dict):
            out.append((i, obj, None))
        else:
            out.append((i, None, "array element is not a JSON object"))
    return out


def _tsv_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "y", "t")


def parse_tsv(text: str) -> ParsedRows:
    """Parse TSV-with-header into (row, obj|None, error|None).

    The header names the columns; every column except the reserved metadata ones
    (``priority``, ``is_gold``, ``gold_expected``) becomes a flat payload field.
    Metadata columns are typed: ``priority`` → int, ``is_gold`` → bool,
    ``gold_expected`` → JSON. A row whose column count doesn't match the header is
    rejected with its line number, so a stray tab is caught rather than silently
    shifting fields.
    """
    numbered = [(i, line) for i, line in enumerate(text.splitlines(), start=1) if line.strip()]
    if not numbered:
        return []
    _, header_line = numbered[0]
    header = header_line.split("\t")
    if not header or any(not h.strip() for h in header):
        return [(numbered[0][0], None, "TSV header has an empty column name")]
    header = [h.strip() for h in header]

    out: ParsedRows = []
    for line_no, line in numbered[1:]:
        cells = line.split("\t")
        if len(cells) != len(header):
            out.append((line_no, None, f"expected {len(header)} columns, got {len(cells)}"))
            continue
        record = dict(zip(header, cells, strict=True))
        payload = {k: v for k, v in record.items() if k not in TSV_RESERVED_COLUMNS}
        obj: dict[str, Any] = {"payload": payload}
        error = None
        if "priority" in record and record["priority"].strip():
            try:
                obj["priority"] = int(record["priority"])
            except ValueError:
                error = f"priority '{record['priority']}' is not an integer"
        if "is_gold" in record:
            obj["is_gold"] = _tsv_bool(record["is_gold"])
        if "gold_expected" in record and record["gold_expected"].strip():
            try:
                obj["gold_expected"] = json.loads(record["gold_expected"])
            except json.JSONDecodeError:
                error = f"gold_expected is not valid JSON: {record['gold_expected']!r}"
        out.append((line_no, None, error) if error else (line_no, obj, None))
    return out


def parse_payload_text(text: str, fmt: str) -> ParsedRows:
    """Dispatch to the parser for ``fmt`` (``jsonl`` | ``json`` | ``tsv``)."""
    if fmt == "jsonl":
        return parse_jsonl(text)
    if fmt == "json":
        return parse_json_array(text)
    if fmt == "tsv":
        return parse_tsv(text)
    raise ValueError(f"unknown format {fmt!r}; expected one of {FORMATS}")


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
