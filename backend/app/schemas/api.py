"""API request/response models (§5)."""

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
