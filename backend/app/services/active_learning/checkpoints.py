"""Checkpoint re-enrollment (§8 step 4) — "register a fine-tuned checkpoint as
the next judge-config version, and enroll it" as one call.

There is deliberately no new concept here. §7.1 already says a versioned judge
config is immutable per version and that attaching one enrolls it as a
``kind=model`` annotator; §7.1's provider-abstraction docstring already names
the punchline — "a fine-tuned checkpoint from the M9 loop is the
OpenAI-compatible provider class, a different ``base_url``, no new code". This
module is that sentence made callable: it is ``judges.new_version`` (or
``create_judge_config`` for the first checkpoint in a line) followed by
``judges.attach_judge``, so a checkpoint's *iteration number* is simply its
``prompt_version`` — the same versioning M7 already gives every judge config,
reused rather than duplicated with a second counter.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JudgeConfig, Project
from app.services.judges.configs import JudgeError, attach_judge, create_judge_config, new_version

__all__ = ["register_checkpoint"]


def _latest_version(db: Session, name: str) -> JudgeConfig | None:
    return db.scalar(
        select(JudgeConfig)
        .where(JudgeConfig.name == name.strip())
        .order_by(JudgeConfig.prompt_version.desc())
        .limit(1)
    )


def register_checkpoint(
    db: Session,
    project_id: int,
    *,
    name: str,
    provider: str,
    model_id: str,
    params: dict[str, Any] | None = None,
    prompt_template: str | None = None,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the next version under ``name`` (or the first) and attach it.

    Unset ``params``/``prompt_template``/``budget`` carry forward from the
    previous checkpoint in the line, exactly like ``POST /judges/{id}:version``
    (§2.5 versioning rules) — a loop that only changes ``model_id`` each
    iteration doesn't have to restate its budget cap every time.
    """
    if db.get(Project, project_id) is None:
        raise JudgeError(f"project {project_id} not found", status=404)

    previous = _latest_version(db, name) if name else None
    if previous is not None:
        overrides: dict[str, Any] = {"provider": provider, "model_id": model_id}
        if params is not None:
            overrides["params"] = params
        if prompt_template is not None:
            overrides["prompt_template"] = prompt_template
        if budget is not None:
            overrides["budget"] = budget
        config = new_version(db, previous.id, **overrides)
    else:
        config = create_judge_config(
            db,
            name=name,
            provider=provider,
            model_id=model_id,
            params=params,
            prompt_template=prompt_template,
            budget=budget,
        )

    enrollment = attach_judge(db, project_id, config.id)
    return {
        "project_id": project_id,
        "judge_config_id": config.id,
        "name": config.name,
        "iteration": config.prompt_version,
        "provider": config.provider,
        "model_id": config.model_id,
        "annotator_id": enrollment["annotator_id"],
    }
