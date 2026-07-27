"""M6 — JSONL exports (§10).

The acceptance bar is "export re-imports cleanly": a ``labels`` export dropped
straight back into ``units:bulk`` has to rebuild the project's units, golds and
all, with no transformation step in between. That round-trip is the headline test
here; the other formats are pinned for shape and provenance.
"""

import json

from sqlalchemy import select

from app.models import Annotator, Template, Unit, User
from app.services.assignment import next_task, submit_label
from app.services.export import ExportError, export_rows, iter_jsonl
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.templates.seed import seed_templates

# --- helpers ----------------------------------------------------------------


def _annotator(db, email: str) -> Annotator:
    user = User(email=email, role="annotator")
    db.add(user)
    db.flush()
    ann = Annotator(kind="human", user_id=user.id, display_name=email, reputation_score=0.9)
    db.add(ann)
    db.flush()
    return ann


def _project(db, name, *, template="image-classification", **kwargs):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == template))
    return create_project(db, name=name, template_id=tmpl.id, **kwargs)


def _ingest(db, project, rows):
    return ingest_units(db, project, parse_jsonl("\n".join(json.dumps(r) for r in rows)))


def _label_everything(db, project, annotators, answer):
    """Fill every open slot, round-robin across annotators."""
    filled = 0
    for ann in annotators:
        while (slot := next_task(db, ann.id, project.id)) is not None:
            submit_label(db, slot.id, ann.id, raw=dict(answer))
            filled += 1
    return filled


# --- labels -----------------------------------------------------------------


def _labels_project(db):
    project = _project(db, "export-labels", labels_per_unit=1, gold_ratio=0.0)
    _ingest(
        db,
        project,
        [
            {"payload": {"image_url": "http://x/1.png"}, "priority": 5},
            {
                "payload": {"image_url": "http://x/2.png"},
                "is_gold": True,
                "gold_expected": {"category": "cat"},
            },
        ],
    )
    _label_everything(db, project, [_annotator(db, "a@x")], {"category": "cat"})
    return project


def test_labels_export_carries_final_label_and_provenance(db) -> None:
    project = _labels_project(db)
    rows = list(export_rows(db, project.id, "labels"))
    assert len(rows) == 2
    row = rows[0]
    assert row["final_label"] == {"category": "cat"}
    assert row["template"]["name"] == "image-classification"
    provenance = row["labels"][0]
    assert provenance["annotator_kind"] == "human"
    assert 0.0 <= provenance["reputation"] <= 1.0
    assert provenance["value"] == {"category": "cat"}


def test_labels_export_reimports_cleanly(db) -> None:
    """§12 M6 acceptance: export → units:bulk → same units, golds intact."""
    source = _labels_project(db)
    exported = "".join(iter_jsonl(db, source.id, "labels"))

    target = _project(db, "reimported", labels_per_unit=1, gold_ratio=0.0)
    report = ingest_units(db, target, parse_jsonl(exported), batch_name="round-trip")

    assert report.rejected_count == 0
    assert report.unit_count == 2

    original = list(db.scalars(select(Unit).where(Unit.project_id == source.id).order_by(Unit.id)))
    copies = list(db.scalars(select(Unit).where(Unit.project_id == target.id).order_by(Unit.id)))
    assert [u.payload for u in copies] == [u.payload for u in original]
    assert [u.is_gold for u in copies] == [u.is_gold for u in original]
    assert [u.gold_expected for u in copies] == [u.gold_expected for u in original]
    assert [u.priority for u in copies] == [u.priority for u in original]


def test_export_is_valid_jsonl(db) -> None:
    project = _labels_project(db)
    text = "".join(iter_jsonl(db, project.id, "labels"))
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 2
    for line in lines:
        assert isinstance(json.loads(line), dict)


# --- raw --------------------------------------------------------------------


def test_raw_export_keeps_the_side_clicked_and_the_item_chosen(db) -> None:
    """The bias-study format (§9): ``raw`` holds the position, ``value`` the item."""
    project = _project(
        db, "sbs", template="side-by-side-preference", labels_per_unit=2, gold_ratio=0.0
    )
    _ingest(db, project, [{"payload": {"prompt": "p", "response_a": "A!", "response_b": "B!"}}])
    _label_everything(
        db, project, [_annotator(db, "a@x"), _annotator(db, "b@x")], {"choice": "Left"}
    )

    rows = list(export_rows(db, project.id, "raw"))
    assert len(rows) == 2
    for row in rows:
        assert row["raw"]["choice"] == "Left"
        # Under AB the left panel is item A; under BA it is item B.
        assert row["value"]["choice"] == row["variant_value"][0]
        assert row["annotator_kind"] == "human"


def test_raw_export_includes_voided_labels_flagged(db) -> None:
    from app.models import Label
    from app.services.slots.lifecycle import void_labels

    project = _labels_project(db)
    label = db.scalar(select(Label))
    void_labels(db, [label])

    rows = list(export_rows(db, project.id, "raw"))
    voided = [r for r in rows if not r["is_valid"]]
    assert len(voided) == 1, "a removed rater's rows must stay visible to a bias study"


# --- preference -------------------------------------------------------------


def test_preference_export_pairs_chosen_against_rejected(db) -> None:
    project = _project(
        db, "sbs", template="side-by-side-preference", labels_per_unit=2, gold_ratio=0.0
    )
    _ingest(
        db,
        project,
        [{"payload": {"prompt": "Explain hashing", "response_a": "good", "response_b": "bad"}}],
    )
    # Both raters pick item A regardless of which side it was shown on: each
    # answers "Left" or "Right" per their own variant, canonicalizing to "A".
    for ann in (_annotator(db, "a@x"), _annotator(db, "b@x")):
        slot = next_task(db, ann.id, project.id)
        side = "Left" if slot.variant["panel_order"] == "AB" else "Right"
        submit_label(db, slot.id, ann.id, raw={"choice": side})

    rows = list(export_rows(db, project.id, "preference"))
    assert len(rows) == 1
    row = rows[0]
    assert row["prompt"] == "Explain hashing"
    assert row["chosen"] == "good"
    assert row["rejected"] == "bad"
    assert row["meta"]["votes_a"] == 2
    assert row["meta"]["votes_b"] == 0
    assert row["meta"]["order_flip_rate"] == 0.0
    assert row["meta"]["mean_annotator_reputation"] is not None


def test_preference_export_skips_units_without_a_winner(db) -> None:
    project = _project(
        db, "sbs", template="side-by-side-preference", labels_per_unit=2, gold_ratio=0.0
    )
    _ingest(db, project, [{"payload": {"prompt": "p", "response_a": "a", "response_b": "b"}}])
    # One rater for A, one for B → a split, not a preference pair.
    for ann in (_annotator(db, "a@x"), _annotator(db, "b@x")):
        slot = next_task(db, ann.id, project.id)
        order = slot.variant["panel_order"]
        want = "A" if ann.display_name == "a@x" else "B"
        side = "Left" if order[0] == want else "Right"
        submit_label(db, slot.id, ann.id, raw={"choice": side})

    assert list(export_rows(db, project.id, "preference")) == []


def test_preference_export_refuses_a_non_comparison_template(db) -> None:
    project = _labels_project(db)
    try:
        list(export_rows(db, project.id, "preference"))
    except ExportError as e:
        assert "comparison template" in str(e)
    else:
        raise AssertionError("expected ExportError")


# --- sft --------------------------------------------------------------------


def test_sft_export_pairs_input_with_the_free_text_answer(db) -> None:
    project = _project(
        db, "transcribe", template="transcription-check", labels_per_unit=1, gold_ratio=0.0
    )
    _ingest(
        db,
        project,
        [{"payload": {"audio_url": "http://x/a.mp3", "transcript": "hello wrld"}}],
    )
    ann = _annotator(db, "a@x")
    slot = next_task(db, ann.id, project.id)
    submit_label(db, slot.id, ann.id, raw={"verdict": "minor errors", "correction": "hello world"})

    rows = list(export_rows(db, project.id, "sft"))
    assert len(rows) == 1
    assert rows[0]["output"] == "hello world"


def test_sft_export_refuses_a_template_with_no_free_text(db) -> None:
    project = _project(db, "img", labels_per_unit=1)
    try:
        list(export_rows(db, project.id, "sft"))
    except ExportError as e:
        assert "free_text" in str(e)
    else:
        raise AssertionError("expected ExportError")


def test_unknown_format_is_rejected(db) -> None:
    project = _project(db, "p", labels_per_unit=1)
    try:
        list(export_rows(db, project.id, "parquet"))
    except ExportError as e:
        assert "unknown export format" in str(e)
    else:
        raise AssertionError("expected ExportError")
