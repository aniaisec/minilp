"""API request/response models (§5)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TemplateOut(BaseModel):
    id: int
    name: str
    version: int
    description: str | None = None
    kind: str
    schema_: dict[str, Any] = Field(alias="schema")

    model_config = {"from_attributes": True, "populate_by_name": True}


class TemplateCreate(BaseModel):
    schema_: dict[str, Any] = Field(alias="schema")

    model_config = {"populate_by_name": True}


class TemplateClone(BaseModel):
    new_name: str | None = None


class PreviewRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class ProjectCreate(BaseModel):
    name: str
    template_id: int
    labels_per_unit: int = 1
    max_labels_per_unit: int | None = None
    guidelines_md: str | None = None
    agreement: dict[str, Any] | None = None
    gold_ratio: float = 0.1
    lease_minutes: int = 30
    min_reputation: float = 0.0
    pipeline: list[dict[str, Any]] | None = None
    description: str | None = None
    config: dict[str, Any] | None = None


class ProjectOut(BaseModel):
    id: int
    name: str
    template_id: int
    template_version: int
    labels_per_unit: int
    max_labels_per_unit: int
    gold_ratio: float

    model_config = {"from_attributes": True}


class BulkIngestRequest(BaseModel):
    jsonl: str = Field(description="Raw JSONL text, one unit object per line.")
    batch_name: str | None = None
    source_filename: str | None = None


class UnitOut(BaseModel):
    id: int
    project_id: int
    batch_id: int | None
    payload: dict[str, Any]
    priority: int
    is_gold: bool
    status: str

    model_config = {"from_attributes": True}


class TaskOut(BaseModel):
    """A leased task handed to an annotator (§5 GET /tasks/next).

    Deliberately blind: never exposes ``is_gold`` — golds must be
    indistinguishable in the UI and in judge prompts (§6.1). The variant is
    included (drives rendering) but carries no A/B identity for the annotator.
    """

    slot_id: int
    unit_id: int
    project_id: int
    payload: dict[str, Any]
    variant: dict[str, Any] | None = None
    lease_expires_at: datetime | None = None


class SubmitRequest(BaseModel):
    raw: dict[str, Any] = Field(description="Exactly what the annotator entered, per input id.")
    value: dict[str, Any] | None = Field(
        default=None,
        description="Canonicalized answer; defaults to raw for variant-free templates.",
    )
    confidence: float | None = None
    reasoning: str | None = None
    comment: str | None = None


class LabelOut(BaseModel):
    id: int
    slot_id: int
    unit_id: int
    annotator_id: int
    value: dict[str, Any]
    is_valid: bool

    model_config = {"from_attributes": True}


class UnitPatch(BaseModel):
    """Adjust a unit's priority and/or void+requeue it (§5 PATCH /units/{id})."""

    priority: int | None = None
    void: bool = Field(default=False, description="Void valid labels and reopen slots.")
