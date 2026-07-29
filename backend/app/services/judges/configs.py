"""Judge configs and enrollment (§7.1, §4).

**Versioning mirrors templates (§2.5).** A judge config is immutable per prompt
version, so an "edit" writes a *new row* sharing the name with
``prompt_version + 1``. Labels reference the annotator, the annotator references
the config row, so every label stays attributable to the exact prompt that
produced it — which is the entire premise of the M9 eval curve ("local-ft-v2 vs
local-ft-v3"). Mutating in place would silently rewrite history for every label
already collected.

**Enrollment creates an annotator (principle 2).** Attaching a judge to a project
creates a ``kind=model`` annotator; from that moment the orchestrator drives the
same ``next``/``submit`` loop humans use, and leasing, gold injection, variant
balance and annotator-unit exclusion apply with no judge-specific code. The
project-side enrollment list lives in ``project.config["judges"]`` — annotators
are not project-scoped in §4 (humans aren't either), so the *project* records who
it enrolled rather than the annotator recording where it works.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Annotator, JudgeConfig, Project
from app.services.judges.providers import PROVIDERS, provider_names


class JudgeError(Exception):
    """A judge operation could not be completed. ``status`` mirrors the HTTP code."""

    def __init__(self, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


# Budget keys accepted in ``judge_configs.budget`` (§4: caps: $/project, $/day,
# max tokens). Unknown keys are rejected at save time rather than ignored — a
# typo'd "daily_usd" that silently disables the cap is exactly the failure mode
# budget caps exist to prevent.
BUDGET_KEYS = frozenset({"project_usd", "daily_usd", "max_tokens", "max_labels"})


def validate_budget(budget: dict[str, Any] | None) -> dict[str, Any] | None:
    if budget is None:
        return None
    if not isinstance(budget, dict):
        raise JudgeError("budget must be an object")
    unknown = sorted(set(budget) - BUDGET_KEYS)
    if unknown:
        raise JudgeError(f"unknown budget keys {unknown}; allowed: {sorted(BUDGET_KEYS)}")
    for key, value in budget.items():
        if value is None:
            continue
        if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
            raise JudgeError(f"budget.{key} must be a non-negative number")
    return budget


def create_judge_config(
    db: Session,
    *,
    name: str,
    provider: str,
    model_id: str,
    params: dict[str, Any] | None = None,
    prompt_template: str | None = None,
    budget: dict[str, Any] | None = None,
) -> JudgeConfig:
    """Create version 1 of a judge config (or the next version of an existing name)."""
    if not name or not name.strip():
        raise JudgeError("judge config needs a name")
    if provider not in PROVIDERS:
        raise JudgeError(f"unknown provider '{provider}'; known: {provider_names()}")
    if not model_id or not model_id.strip():
        raise JudgeError("judge config needs a model_id")

    latest = db.scalar(
        select(func.max(JudgeConfig.prompt_version)).where(JudgeConfig.name == name.strip())
    )
    config = JudgeConfig(
        name=name.strip(),
        provider=provider,
        model_id=model_id.strip(),
        params=params or {},
        prompt_template=prompt_template,
        prompt_version=(latest or 0) + 1,
        budget=validate_budget(budget),
    )
    db.add(config)
    db.flush()
    return config


def new_version(db: Session, judge_config_id: int, **changes: Any) -> JudgeConfig:
    """Write the next version of a config, carrying forward anything unchanged."""
    current = db.get(JudgeConfig, judge_config_id)
    if current is None:
        raise JudgeError(f"judge config {judge_config_id} not found", status=404)
    return create_judge_config(
        db,
        name=changes.get("name", current.name),
        provider=changes.get("provider", current.provider),
        model_id=changes.get("model_id", current.model_id),
        params=changes.get("params", current.params),
        prompt_template=changes.get("prompt_template", current.prompt_template),
        budget=changes.get("budget", current.budget),
    )


def list_judge_configs(db: Session, *, name: str | None = None) -> list[JudgeConfig]:
    stmt = select(JudgeConfig).order_by(JudgeConfig.name, JudgeConfig.prompt_version.desc())
    if name:
        stmt = stmt.where(JudgeConfig.name == name)
    return list(db.scalars(stmt))


def judge_display_name(config: JudgeConfig) -> str:
    return f"{config.name} v{config.prompt_version}"


def annotator_for(db: Session, config: JudgeConfig) -> Annotator:
    """The ``kind=model`` annotator for this config version, created on demand.

    One annotator per config *version*, not per config name: a new prompt version
    is a new rater, and letting v2's labels land under v1's annotator would merge
    two different judges' reputations into one meaningless number.
    """
    existing = db.scalar(
        select(Annotator).where(Annotator.judge_config_id == config.id, Annotator.kind == "model")
    )
    if existing is not None:
        return existing
    annotator = Annotator(
        kind="model",
        display_name=judge_display_name(config),
        judge_config_id=config.id,
        status="active",
    )
    db.add(annotator)
    db.flush()
    return annotator


def enrolled_judges(project: Project) -> list[dict[str, Any]]:
    """The project's enrollment list, normalized."""
    entries = ((project.config or {}).get("judges")) or []
    out: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("judge_config_id") is not None:
            out.append(
                {
                    "judge_config_id": int(entry["judge_config_id"]),
                    "annotator_id": entry.get("annotator_id"),
                }
            )
    return out


def attach_judge(db: Session, project_id: int, judge_config_id: int) -> dict[str, Any]:
    """Enroll a judge on a project as an annotator (§5 ``judges/{jid}:attach``).

    Idempotent: attaching twice returns the same annotator rather than creating a
    second rater for the same config, which would double every judge's vote.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise JudgeError(f"project {project_id} not found", status=404)
    config = db.get(JudgeConfig, judge_config_id)
    if config is None:
        raise JudgeError(f"judge config {judge_config_id} not found", status=404)

    annotator = annotator_for(db, config)
    entries = enrolled_judges(project)
    if not any(e["judge_config_id"] == config.id for e in entries):
        entries.append({"judge_config_id": config.id, "annotator_id": annotator.id})
        # Reassign rather than mutate: SQLAlchemy does not track in-place edits to
        # a JSONB dict, so a mutated config would never reach the database.
        project.config = {**(project.config or {}), "judges": entries}
        db.flush()
    return {
        "project_id": project.id,
        "judge_config_id": config.id,
        "annotator_id": annotator.id,
        "display_name": judge_display_name(config),
    }


def detach_judge(db: Session, project_id: int, judge_config_id: int) -> dict[str, Any]:
    """Remove a judge from a project's enrollment list.

    The annotator and its labels stay: detaching means "stop giving it work", not
    "erase what it already contributed" — which would silently change every
    agreement number the project has reported.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise JudgeError(f"project {project_id} not found", status=404)
    entries = [e for e in enrolled_judges(project) if e["judge_config_id"] != judge_config_id]
    project.config = {**(project.config or {}), "judges": entries}
    db.flush()
    return {"project_id": project_id, "enrolled": entries}


def resolve_enrollment(db: Session, project: Project, judge_config_id: int) -> Annotator:
    """The annotator a run should act as, refusing an unenrolled judge."""
    entries = enrolled_judges(project)
    match = next((e for e in entries if e["judge_config_id"] == judge_config_id), None)
    if match is None:
        raise JudgeError(
            f"judge config {judge_config_id} is not enrolled on project {project.id}; "
            "attach it first",
            status=409,
        )
    annotator = db.get(Annotator, match["annotator_id"]) if match.get("annotator_id") else None
    if annotator is None:
        config = db.get(JudgeConfig, judge_config_id)
        if config is None:
            raise JudgeError(f"judge config {judge_config_id} not found", status=404)
        annotator = annotator_for(db, config)
    return annotator
