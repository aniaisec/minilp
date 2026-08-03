"""Marketplace bundles against real PostgreSQL (§12, M10).

The M10 acceptance criterion from PLAN.md: "an exported bundle re-imports and
round-trips validate -> preview, same guarantee as gallery templates (M1)."
Each test below is named after one part of that guarantee, plus the surrounding
behavior: credential-freeness, name collisions, and the local shared directory.
"""

import json

import pytest
from sqlalchemy import select

from app.models import Project, Template
from app.services.judges import JudgeError, attach_judge, create_judge_config, enrolled_judges
from app.services.marketplace import (
    BUNDLE_VERSION,
    LocalBundleError,
    MarketplaceError,
    export_judge_config_bundle,
    export_project_bundle,
    export_template_bundle,
    import_bundle,
    list_local_bundles,
    read_local_bundle,
)
from app.services.projects import create_project
from app.services.templates.preview import render_preview
from app.services.templates.sample import get_sample
from app.services.templates.seed import seed_templates
from app.services.templates.validation import TemplateValidationError, validate_template

# --- helpers ------------------------------------------------------------------


def _gallery_template(db, name="side-by-side-preference") -> Template:
    seed_templates(db)
    return db.scalar(select(Template).where(Template.name == name))


def _project(db, *, template="image-classification", **kwargs) -> Project:
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == template))
    kwargs.setdefault("gold_ratio", 0.0)
    return create_project(db, name="marketplace-source", template_id=tmpl.id, **kwargs)


# --- template bundles -----------------------------------------------------------


def test_exported_template_bundle_round_trips_validate_then_preview(db) -> None:
    """M1's own acceptance test, extended to a bundle: export a gallery
    template, import it as a fresh custom template, and the imported schema
    still validates and previews — the exact guarantee PLAN.md's M10 line
    promises."""
    original = _gallery_template(db)
    bundle = export_template_bundle(original)
    assert bundle["bundle_version"] == BUNDLE_VERSION
    assert bundle["kind"] == "template"

    result = import_bundle(db, bundle)
    imported = result["template"]
    assert imported.id != original.id
    assert imported.kind == "custom"  # imports never masquerade as builtin

    validate_template(imported.schema)  # already validated by create_template; re-asserted here
    sample = get_sample(db, imported)
    preview = render_preview(imported.schema, sample["sample"])
    assert preview["inputs"]  # rendered with hotkeys assigned, not an empty shell


def test_a_saved_sample_travels_with_the_bundle_and_previews_immediately(db) -> None:
    original = _gallery_template(db, "image-classification")
    original.sample = {"image_url": "http://x/cat.png", "context": "a photo of a cat"}
    db.add(original)
    db.flush()

    bundle = export_template_bundle(original)
    assert bundle["sample"] == original.sample

    imported = import_bundle(db, bundle)["template"]
    assert imported.sample == original.sample
    # No regeneration needed — the imported sample previews as-is.
    render_preview(imported.schema, imported.sample)


def test_importing_the_same_template_bundle_twice_does_not_collide(db) -> None:
    original = _gallery_template(db)
    bundle = export_template_bundle(original)

    first = import_bundle(db, bundle)["template"]
    second = import_bundle(db, bundle)["template"]

    assert first.name != second.name
    assert second.name.startswith(original.name)
    assert first.version == second.version == 1


def test_importing_a_malformed_template_bundle_reuses_the_real_validator(db) -> None:
    bundle = {
        "bundle_version": BUNDLE_VERSION,
        "kind": "template",
        "name": "broken",
        "template": {
            "name": "broken",
            "inputs": [{"id": "x", "type": "radio", "options": ["only-one"]}],
        },
    }
    with pytest.raises(TemplateValidationError):
        import_bundle(db, bundle)
    # Nothing was created — the failed import left no half-written row.
    assert db.scalar(select(Template).where(Template.name == "broken")) is None


# --- judge config bundles -------------------------------------------------------


def test_exported_judge_config_bundle_never_carries_a_credential(db) -> None:
    config = create_judge_config(
        db,
        name="claude-judge",
        provider="anthropic",
        model_id="claude-x",
        params={"api_key_env": "ANTHROPIC_API_KEY", "temperature": 0.0},
    )
    bundle = export_judge_config_bundle(config)
    blob = json.dumps(bundle)

    assert bundle["kind"] == "judge_config"
    assert bundle["judge_config"]["params"]["api_key_env"] == "ANTHROPIC_API_KEY"
    # The only thing stored is the *name* of an env var — never a literal secret.
    assert "sk-" not in blob
    assert "secret" not in blob.lower()


def test_imported_judge_config_bundle_creates_a_working_config(db) -> None:
    config = create_judge_config(
        db, name="mock-judge", provider="mock", model_id="mock-1", budget={"project_usd": 1.0}
    )
    bundle = export_judge_config_bundle(config)

    result = import_bundle(db, bundle)
    imported = result["judge_config"]
    assert imported.id != config.id
    assert imported.provider == "mock"
    assert imported.budget == {"project_usd": 1.0}
    # Unlike templates (renamed on collision), a same-named judge config versions
    # forward — the exact behavior create_judge_config already gives POST /judges,
    # so importing a bundle for a name you already have just adds to its lineage
    # rather than refusing or silently shadowing it.
    assert imported.prompt_version == config.prompt_version + 1


def test_importing_a_judge_config_bundle_with_a_fresh_name_starts_at_version_1(db) -> None:
    bundle = export_judge_config_bundle(
        create_judge_config(db, name="brand-new-judge", provider="mock", model_id="mock-1")
    )
    # Import into a name that doesn't exist yet in *this* db — simulate a fresh
    # instance by importing under a name nothing local shares.
    bundle["judge_config"]["name"] = "totally-unique-judge-name"
    imported = import_bundle(db, bundle)["judge_config"]
    assert imported.prompt_version == 1


def test_importing_a_judge_config_bundle_with_an_unknown_provider_is_rejected(db) -> None:
    bundle = {
        "bundle_version": BUNDLE_VERSION,
        "kind": "judge_config",
        "judge_config": {"name": "x", "provider": "vibes", "model_id": "m"},
    }
    with pytest.raises(JudgeError):
        import_bundle(db, bundle)


# --- project bundles -------------------------------------------------------------


def test_exported_project_bundle_carries_template_judges_and_pipeline(db) -> None:
    project = _project(
        db,
        pipeline=[
            {"stage": "ensemble", "merge": "calibration_weighted"},
            {"stage": "auto_finalize", "if": "consensus >= 0.9"},
            {"stage": "human_review", "else": True},
        ],
        guidelines_md="Be careful.",
    )
    judge = create_judge_config(db, name="j", provider="mock", model_id="mock-1")
    attach_judge(db, project.id, judge.id)

    bundle = export_project_bundle(db, project)
    assert bundle["kind"] == "project"
    assert bundle["template"]["name"] == "image-classification"
    assert len(bundle["judge_configs"]) == 1
    assert bundle["judge_configs"][0]["name"] == "j"
    assert bundle["project"]["guidelines_md"] == "Be careful."
    assert bundle["project"]["pipeline"][1]["if"] == "consensus >= 0.9"
    # Units/labels are deliberately absent — this is a starter kit, not a backup.
    assert "units" not in bundle
    assert "labels" not in bundle


def test_imported_project_bundle_recreates_a_working_project(db) -> None:
    source = _project(db, guidelines_md="Original guidelines.", labels_per_unit=1)
    judge = create_judge_config(db, name="j", provider="mock", model_id="mock-1")
    attach_judge(db, source.id, judge.id)
    bundle = export_project_bundle(db, source)

    result = import_bundle(db, bundle, create_project_row=True)
    new_project = result["project"]
    assert new_project.id != source.id
    assert new_project.template_id != source.template_id  # its own imported template
    assert new_project.guidelines_md == "Original guidelines."

    entries = enrolled_judges(new_project)
    assert len(entries) == 1
    assert entries[0]["judge_config_id"] == result["judge_configs"][0].id
    assert entries[0]["judge_config_id"] != judge.id  # its own imported judge, not the source's


def test_project_bundle_import_can_skip_creating_the_project_row(db) -> None:
    source = _project(db)
    judge = create_judge_config(db, name="j", provider="mock", model_id="mock-1")
    attach_judge(db, source.id, judge.id)
    bundle = export_project_bundle(db, source)

    before = db.scalar(select(Project.id).order_by(Project.id.desc()))
    result = import_bundle(db, bundle, create_project_row=False)
    after = db.scalar(select(Project.id).order_by(Project.id.desc()))

    assert "project" not in result
    assert after == before  # no new project row
    assert result["template"] is not None
    assert len(result["judge_configs"]) == 1


# --- bundle-level errors ---------------------------------------------------------


def test_unsupported_bundle_version_is_rejected(db) -> None:
    with pytest.raises(MarketplaceError):
        import_bundle(db, {"bundle_version": 999, "kind": "template", "template": {}})


def test_unknown_bundle_kind_is_rejected(db) -> None:
    with pytest.raises(MarketplaceError):
        import_bundle(db, {"bundle_version": BUNDLE_VERSION, "kind": "vibes"})


# --- the local shared-bundle directory --------------------------------------------


def test_local_bundle_directory_lists_the_shipped_bundles() -> None:
    bundles = list_local_bundles()
    names = {b["filename"] for b in bundles}
    assert {
        "summarization-quality.json",
        "calibrated-mock-judge.json",
        "toxicity-triage.json",
    } <= names
    kinds = {b["filename"]: b["kind"] for b in bundles}
    assert kinds["summarization-quality.json"] == "template"
    assert kinds["calibrated-mock-judge.json"] == "judge_config"
    assert kinds["toxicity-triage.json"] == "project"


@pytest.mark.parametrize(
    "filename", ["summarization-quality.json", "calibrated-mock-judge.json", "toxicity-triage.json"]
)
def test_every_shipped_bundle_imports_cleanly(db, filename: str) -> None:
    """The M1 gallery guarantee, extended to what ships in the marketplace
    directory: every bundle the repo carries actually imports."""
    bundle = read_local_bundle(filename)
    result = import_bundle(db, bundle)
    assert result["kind"] == bundle["kind"]


def test_reading_an_unknown_local_bundle_is_a_clear_error() -> None:
    with pytest.raises(LocalBundleError):
        read_local_bundle("does-not-exist.json")


def test_reading_a_local_bundle_refuses_path_traversal() -> None:
    with pytest.raises(LocalBundleError):
        read_local_bundle("../../etc/passwd")
    with pytest.raises(LocalBundleError):
        read_local_bundle("../bundle.py")
