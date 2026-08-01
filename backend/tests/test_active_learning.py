"""M9 — active-learning loop (§8): informativeness ranking, checkpoint
re-enrollment, the iteration eval curve.

Mirrors ``test_merge.py``'s style: synthetic judges of known, pinned answers
make the accuracy numbers exact rather than approximate, so the "improving
over N iterations" claim is asserted on hard numbers, not a trend line.
"""

import json

import pytest
from sqlalchemy import select

from app.models import Annotator, JudgeConfig, Template, Unit, User
from app.services.active_learning import (
    agreement_vs_final,
    iteration_curve,
    rank_batch,
    register_checkpoint,
)
from app.services.assignment import next_task, submit_label
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.judges import (
    JudgeError,
    attach_judge,
    create_judge_config,
    enrolled_judges,
    run_judge,
)
from app.services.merge import decide
from app.services.projects import create_project
from app.services.templates.seed import seed_templates

# --- helpers ------------------------------------------------------------------


def _annotator(db, email: str) -> Annotator:
    user = User(email=email, role="annotator")
    db.add(user)
    db.flush()
    ann = Annotator(kind="human", user_id=user.id, display_name=email)
    db.add(ann)
    db.flush()
    return ann


def _project(db, name, *, template="image-classification", **kwargs):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == template))
    kwargs.setdefault("gold_ratio", 0.0)
    return create_project(db, name=name, template_id=tmpl.id, **kwargs)


def _rows(n, *, expected=None):
    rows = []
    for i in range(n):
        row = {"payload": {"image_url": f"http://x/{i}.png"}}
        if expected is not None:
            answer = expected[i] if isinstance(expected, list) else expected
            row["is_gold"] = True
            row["gold_expected"] = {"category": answer}
        rows.append(json.dumps(row))
    return rows


def _ingest(db, project, rows):
    return ingest_units(db, project, parse_jsonl("\n".join(rows)))


def _submit(db, annotator, project, raw, **kwargs):
    slot = next_task(db, annotator.id, project.id)
    assert slot is not None, "expected an open slot"
    return submit_label(db, slot.id, annotator.id, raw=raw, **kwargs)


def _judge(db, name, *, answer=None, confidence=None):
    mock: dict = {}
    if answer is not None:
        mock["answers"] = {"category": answer}
    if confidence is not None:
        mock["confidence"] = confidence
    return create_judge_config(
        db, name=name, provider="mock", model_id="mock-1", params={"mock": mock} if mock else None
    )


# --- batch selection ----------------------------------------------------------


def test_batch_ranks_disagreement_over_agreement_and_excludes_finalized_units(db):
    """A unit two raters disagree on outranks one they agree on — and the
    agreed unit, having auto-finalized, isn't even in the pool (§8 step 1)."""
    project = _project(db, "al-batch", labels_per_unit=2)
    _ingest(db, project, _rows(2))

    a, b = _annotator(db, "a@x"), _annotator(db, "b@x")

    # Unit 1 (row 0): disagreement.
    _submit(db, a, project, {"category": "cat"})
    _submit(db, b, project, {"category": "dog"})
    # Unit 2 (row 1): unanimous -> auto-finalizes, drops out of the pool.
    _submit(db, a, project, {"category": "cat"})
    _submit(db, b, project, {"category": "cat"})

    result = rank_batch(db, project.id, limit=10)
    assert result["pool_size"] == 1, "the finalized unit must not be scored at all"
    assert len(result["units"]) == 1
    top = result["units"][0]
    assert top["disagreement"] == 0.5
    assert top["entropy"] == 1.0  # two raters, evenly split


def test_batch_gives_a_fresh_unlabeled_unit_the_neutral_score(db):
    """No votes, no judge confidence: nothing indicates the unit is hard, so it
    scores at the documented neutral midpoint rather than crashing the ranking."""
    project = _project(db, "al-fresh", labels_per_unit=1)
    _ingest(db, project, _rows(1))

    result = rank_batch(db, project.id, limit=10)
    assert result["units"][0]["score"] == 0.5
    assert result["units"][0]["disagreement"] is None
    assert result["units"][0]["confidence"] is None


def test_batch_weighs_in_the_students_own_low_confidence(db):
    """With ``judge_config_id`` set, a low-confidence answer from *that* judge
    raises informativeness on top of ensemble disagreement."""
    project = _project(db, "al-confidence", labels_per_unit=2)
    _ingest(db, project, _rows(1))
    judge = _judge(db, "student", answer="cat", confidence=0.1)
    attach_judge(db, project.id, judge.id)
    human = _annotator(db, "h@x")

    run_judge(db, project.id, judge.id, limit=1)
    _submit(db, human, project, {"category": "dog"})  # disagreement -> escalates, stays in pool

    plain = rank_batch(db, project.id, limit=10)["units"][0]
    weighted = rank_batch(db, project.id, limit=10, judge_config_id=judge.id)["units"][0]
    assert weighted["confidence"] == pytest.approx(0.1, abs=1e-6)
    assert weighted["score"] > plain["score"]


def test_batch_limit_and_ordering(db):
    project = _project(db, "al-limit", labels_per_unit=2)
    _ingest(db, project, _rows(3))
    a, b = _annotator(db, "a@x"), _annotator(db, "b@x")
    for _ in range(3):
        _submit(db, a, project, {"category": "cat"})
        _submit(db, b, project, {"category": "dog"})

    result = rank_batch(db, project.id, limit=2)
    assert len(result["units"]) == 2
    assert result["pool_size"] == 3


def test_batch_on_unknown_project_raises(db):
    with pytest.raises(ValueError, match="not found"):
        rank_batch(db, 999999, limit=5)


def test_batch_dedupe_drops_a_near_duplicate_embedding(db):
    project = _project(db, "al-dedupe", labels_per_unit=2)
    rows = [
        json.dumps({"payload": {"image_url": "http://x/0.png", "embedding": [1.0, 0.0, 0.0]}}),
        json.dumps({"payload": {"image_url": "http://x/1.png", "embedding": [1.0, 0.0, 0.001]}}),
        json.dumps({"payload": {"image_url": "http://x/2.png", "embedding": [0.0, 1.0, 0.0]}}),
    ]
    _ingest(db, project, rows)
    a, b = _annotator(db, "a@x"), _annotator(db, "b@x")
    for _ in range(3):
        _submit(db, a, project, {"category": "cat"})
        _submit(db, b, project, {"category": "dog"})

    result = rank_batch(db, project.id, limit=10, dedupe_field="embedding", dedupe_threshold=0.99)
    assert result["pool_size"] == 3
    assert result["dropped_by_dedupe"] == 1
    assert len(result["units"]) == 2


# --- checkpoint re-enrollment ---------------------------------------------------


def test_register_checkpoint_creates_v1_and_attaches(db):
    project = _project(db, "al-ckpt")
    out = register_checkpoint(db, project.id, name="local-ft", provider="mock", model_id="ckpt-v1")
    assert out["iteration"] == 1
    assert out["annotator_id"] is not None
    entries = enrolled_judges(project)
    assert any(e["judge_config_id"] == out["judge_config_id"] for e in entries)


def test_register_checkpoint_bumps_version_on_the_same_name(db):
    project = _project(db, "al-ckpt-v2")
    v1 = register_checkpoint(db, project.id, name="local-ft", provider="mock", model_id="ckpt-v1")
    v2 = register_checkpoint(db, project.id, name="local-ft", provider="mock", model_id="ckpt-v2")
    assert (v1["iteration"], v2["iteration"]) == (1, 2)
    assert v1["judge_config_id"] != v2["judge_config_id"]
    # Both stay enrolled; re-enrolling never silently detaches the previous one.
    assert len(enrolled_judges(project)) == 2


def test_register_checkpoint_carries_forward_unset_budget(db):
    project = _project(db, "al-ckpt-budget")
    register_checkpoint(
        db,
        project.id,
        name="local-ft",
        provider="mock",
        model_id="ckpt-v1",
        budget={"max_labels": 5},
    )
    v2 = register_checkpoint(db, project.id, name="local-ft", provider="mock", model_id="ckpt-v2")
    config = db.get(JudgeConfig, v2["judge_config_id"])
    assert config.budget == {"max_labels": 5}


def test_register_checkpoint_on_unknown_project_is_a_judge_error(db):
    with pytest.raises(JudgeError):
        register_checkpoint(db, 999999, name="x", provider="mock", model_id="m")


# --- iteration eval curve -------------------------------------------------------


def test_iteration_curve_tracks_improving_gold_accuracy_across_versions(db):
    """A toy student model improving over 3 iterations (§12 M9 demo). Each
    iteration labels its own fresh batch of 6 golds (1 bird, 2 dog, 3 cat) with
    a pinned answer, so gold accuracy is exact: 1/6, then 2/6, then 3/6."""
    # gold_threshold=0 turns off the pause-and-void cliff (§6.1): that gate exists
    # for real annotators, and would otherwise void a deliberately-imperfect
    # early checkpoint's labels out from under this test, same as test_merge.py's
    # synthetic-judges test switches it off for the same reason.
    project = _project(
        db,
        "al-iterations",
        labels_per_unit=1,
        gold_ratio=1.0,
        config={"quality": {"gold_threshold": 0.0}},
    )
    expected = ["bird", "dog", "dog", "cat", "cat", "cat"]

    checkpoints = []
    for version_answer in ("bird", "dog", "cat"):
        _ingest(db, project, _rows(6, expected=expected))
        ckpt = register_checkpoint(
            db,
            project.id,
            name="student",
            provider="mock",
            model_id=f"ckpt-{version_answer}",
            params={"mock": {"answers": {"category": version_answer}}},
        )
        run_judge(db, project.id, ckpt["judge_config_id"], limit=6)
        checkpoints.append(ckpt)

    curve = iteration_curve(db, project.id, "student")
    rates = [p["gold_accuracy"]["rate"] for p in curve["iterations"]]
    assert rates == [
        pytest.approx(1 / 6, abs=1e-3),
        pytest.approx(2 / 6, abs=1e-3),
        pytest.approx(3 / 6, abs=1e-3),
    ]
    assert rates[0] < rates[1] < rates[2], "the whole point: accuracy improves each iteration"
    assert [p["iteration"] for p in curve["iterations"]] == [1, 2, 3]
    assert all(p["label_count"] == 6 for p in curve["iterations"])
    # K=1: each unit's lone vote always "agrees with itself" and auto-finalizes
    # to whatever the judge said, so the decided answer always matches the label.
    assert all(p["agreement_vs_final"]["comparisons"] == 6 for p in curve["iterations"])
    assert all(p["agreement_vs_final"]["agreements"] == 6 for p in curve["iterations"])


def test_iteration_curve_on_unknown_project_or_name_raises(db):
    project = _project(db, "al-iter-404")
    with pytest.raises(ValueError, match="project"):
        iteration_curve(db, 999999, "student")
    with pytest.raises(ValueError, match="no judge config"):
        iteration_curve(db, project.id, "does-not-exist")


def test_agreement_vs_final_reflects_a_human_override(db):
    """A reviewer overriding the ensemble is exactly the case peer-agreement
    can't see but ``final_labels`` can (§7.2) — the eval curve must track it."""
    project = _project(
        db,
        "al-override",
        labels_per_unit=2,
        gold_ratio=0.0,
        config={"quality": {"on_disagreement": "escalate"}},
    )
    _ingest(db, project, _rows(1))
    judge = _judge(db, "student", answer="cat")
    attach_judge(db, project.id, judge.id)
    run_judge(db, project.id, judge.id, limit=1)
    human = _annotator(db, "h@x")
    _submit(db, human, project, {"category": "dog"})  # disagreement -> escalated

    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    decide(db, unit.id, decision="override", value={"category": "dog"})

    judge_annotator = db.scalar(
        select(Annotator).where(Annotator.judge_config_id == judge.id, Annotator.kind == "model")
    )
    agreements, comparisons = agreement_vs_final(db, judge_annotator.id, project.id)
    assert (agreements, comparisons) == (0, 1), "the judge said cat; the human decided dog"
