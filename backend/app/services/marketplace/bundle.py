"""Marketplace bundles (§12, M10) — export a template, judge config, or whole
project starter kit as a shareable, credential-free JSON document; import re-runs
the exact validation path units already go through (§2.1), so an imported bundle
gets no special treatment and no special trust — the same guarantee a gallery
template gets at boot (M1 acceptance: validate -> preview).

Nothing here is a new table. §4 already carries every table a bundle touches
(``templates``, ``judge_configs``, ``projects``) — a bundle is a *view* over rows
that exist, not a new persistence layer, which is why M10 needed no migration.

**Never a credential.** A judge config only ever stores ``params.api_key_env`` —
the *name* of an environment variable the server reads at call time (§7.1,
docs/DESIGN.md "API keys are named, never stored") — so a judge-config bundle is
shareable exactly as-is.

**A project bundle is a starter kit, not a backup.** It carries the template, the
enrolled judge configs, and the project's non-data configuration (guidelines,
overlap, gold ratio, routing pipeline). Units and labels stay behind —
``/projects/{id}/export`` (§10) is the tool for a project's *data*.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JudgeConfig, Project, Template
from app.services.judges.configs import (
    JudgeError,
    attach_judge,
    create_judge_config,
    enrolled_judges,
)
from app.services.projects.service import ProjectError, create_project
from app.services.templates.repository import create_template
from app.services.templates.validation import TemplateValidationError

BUNDLE_VERSION = 1
BUNDLE_KINDS = ("template", "judge_config", "project")


class MarketplaceError(ValueError):
    """A bundle could not be exported or imported. Not a validation error itself —
    ``TemplateValidationError``/``JudgeError``/``ProjectError`` are re-raised as-is
    so the caller gets the same error shape a direct ``POST /templates`` or
    ``POST /judges`` call would produce."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _judge_config_payload(config: JudgeConfig) -> dict[str, Any]:
    return {
        "name": config.name,
        "provider": config.provider,
        "model_id": config.model_id,
        "params": config.params,
        "prompt_template": config.prompt_template,
        "budget": config.budget,
    }


def _unique_template_name(db: Session, name: str) -> str:
    """Avoid colliding with an existing template name (builtin or custom) on
    import — ``templates`` is unique on ``(name, version)`` and every import
    lands at version 1, so a same-named target would otherwise fail with a raw
    integrity error instead of a readable bundle problem."""
    candidate = name
    n = 1
    while db.scalar(select(Template.id).where(Template.name == candidate)) is not None:
        n += 1
        candidate = f"{name} (imported {n - 1})"
    return candidate


# --- export ------------------------------------------------------------------


def export_template_bundle(template: Template) -> dict[str, Any]:
    """A template as a shareable bundle. Carries ``sample`` when the template has
    one saved, so an imported template previews immediately (§11) without waiting
    on the generate-on-demand fallback."""
    return {
        "bundle_version": BUNDLE_VERSION,
        "kind": "template",
        "name": template.name,
        "description": template.description,
        "exported_at": _now(),
        "template": copy.deepcopy(template.schema),
        "sample": copy.deepcopy(template.sample) if template.sample else None,
    }


def export_judge_config_bundle(config: JudgeConfig) -> dict[str, Any]:
    """A judge config as a shareable bundle — never carries a credential."""
    return {
        "bundle_version": BUNDLE_VERSION,
        "kind": "judge_config",
        "name": config.name,
        "description": None,
        "exported_at": _now(),
        "judge_config": _judge_config_payload(config),
    }


def export_project_bundle(db: Session, project: Project) -> dict[str, Any]:
    """A project's template + enrolled judge configs + non-data config, as one
    shareable starter-kit bundle."""
    template = db.get(Template, project.template_id)
    if template is None:
        raise MarketplaceError(f"project {project.id} references a missing template")

    judge_configs = []
    for entry in enrolled_judges(project):
        config = db.get(JudgeConfig, entry["judge_config_id"])
        if config is not None:
            judge_configs.append(_judge_config_payload(config))

    return {
        "bundle_version": BUNDLE_VERSION,
        "kind": "project",
        "name": project.name,
        "description": project.description,
        "exported_at": _now(),
        "template": copy.deepcopy(template.schema),
        "sample": copy.deepcopy(template.sample) if template.sample else None,
        "judge_configs": judge_configs,
        "project": {
            "guidelines_md": project.guidelines_md,
            "labels_per_unit": project.labels_per_unit,
            "max_labels_per_unit": project.max_labels_per_unit,
            "agreement": project.agreement,
            "gold_ratio": project.gold_ratio,
            "lease_minutes": project.lease_minutes,
            "min_reputation": project.min_reputation,
            "pipeline": project.pipeline,
        },
    }


# --- import ------------------------------------------------------------------


def _import_template(db: Session, bundle: dict[str, Any]) -> Template:
    schema = bundle.get("template")
    if not isinstance(schema, dict):
        raise MarketplaceError("bundle is missing a 'template' object")
    schema = copy.deepcopy(schema)
    name = schema.get("name") or bundle.get("name") or "imported-template"
    schema["name"] = _unique_template_name(db, name)
    schema["version"] = 1

    # Same call POST /templates makes — an imported template gets no special
    # trust. A validation failure re-raises TemplateValidationError untouched so
    # the API layer can translate it exactly as it does for a hand-authored one.
    template = create_template(db, schema, kind="custom")

    sample = bundle.get("sample")
    if sample:
        template.sample = sample
        db.add(template)
        db.flush()
    return template


def _import_judge_config(db: Session, payload: dict[str, Any]) -> JudgeConfig:
    if not isinstance(payload, dict):
        raise MarketplaceError("judge_config bundle entry must be an object")
    missing = [k for k in ("name", "provider", "model_id") if not payload.get(k)]
    if missing:
        raise MarketplaceError(f"judge_config bundle is missing {missing}")
    # Same call POST /judges makes — unknown providers / bad budgets raise
    # JudgeError exactly as they would from the API.
    return create_judge_config(
        db,
        name=payload["name"],
        provider=payload["provider"],
        model_id=payload["model_id"],
        params=payload.get("params"),
        prompt_template=payload.get("prompt_template"),
        budget=payload.get("budget"),
    )


def import_bundle(
    db: Session, bundle: dict[str, Any], *, create_project_row: bool = True
) -> dict[str, Any]:
    """Import a bundle, dispatching on ``kind``.

    Every kind reuses the exact service call its own ``POST`` endpoint makes
    (``create_template`` / ``create_judge_config`` / ``create_project``), so an
    imported bundle is validated identically to something typed in by hand — the
    M1 gallery guarantee (validate -> preview) extended to anything shareable.

    ``create_project_row`` only affects ``kind == "project"``: when true (the
    default) the bundle also creates a live ``Project`` bound to the imported
    template with the imported judges attached — "re-import into a fresh
    instance" (§14 v3) meaning a working project, not just orphaned config rows.
    """
    if not isinstance(bundle, dict):
        raise MarketplaceError("bundle must be a JSON object")
    version = bundle.get("bundle_version")
    if version != BUNDLE_VERSION:
        raise MarketplaceError(
            f"unsupported bundle_version {version!r}; this instance reads {BUNDLE_VERSION}"
        )
    kind = bundle.get("kind")
    if kind not in BUNDLE_KINDS:
        raise MarketplaceError(f"unknown bundle kind {kind!r}; expected one of {BUNDLE_KINDS}")

    if kind == "template":
        template = _import_template(db, bundle)
        return {"kind": "template", "template": template}

    if kind == "judge_config":
        payload = bundle.get("judge_config")
        if not isinstance(payload, dict):
            raise MarketplaceError("bundle is missing a 'judge_config' object")
        config = _import_judge_config(db, payload)
        return {"kind": "judge_config", "judge_config": config}

    # kind == "project"
    template = _import_template(db, bundle)
    configs = [_import_judge_config(db, payload) for payload in (bundle.get("judge_configs") or [])]

    result: dict[str, Any] = {"kind": "project", "template": template, "judge_configs": configs}

    if create_project_row:
        pconf = bundle.get("project") or {}
        project = create_project(
            db,
            name=bundle.get("name") or template.name,
            description=bundle.get("description"),
            template_id=template.id,
            labels_per_unit=pconf.get("labels_per_unit", 1),
            max_labels_per_unit=pconf.get("max_labels_per_unit"),
            guidelines_md=pconf.get("guidelines_md"),
            agreement=pconf.get("agreement"),
            gold_ratio=pconf.get("gold_ratio", 0.1),
            lease_minutes=pconf.get("lease_minutes", 30),
            min_reputation=pconf.get("min_reputation", 0.0),
            pipeline=pconf.get("pipeline"),
        )
        for config in configs:
            attach_judge(db, project.id, config.id)
        result["project"] = project

    return result


__all__ = [
    "BUNDLE_KINDS",
    "BUNDLE_VERSION",
    "JudgeError",
    "MarketplaceError",
    "ProjectError",
    "TemplateValidationError",
    "export_judge_config_bundle",
    "export_project_bundle",
    "export_template_bundle",
    "import_bundle",
]
