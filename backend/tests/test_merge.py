"""M8 acceptance suite — merge, routing and finalization against real PostgreSQL (§7.2).

§12's M8 acceptance criteria for the backend half have a test each, named after
them:

- ``test_synthetic_judges_with_known_accuracies_converge_to_merge_weights``
- ``test_a_disagreeing_unit_routes_to_review_and_an_override_is_recorded``
- ``test_the_backlog_webhook_fires_past_its_threshold``

plus the surrounding behavior: what the merge does with tolerance rules and
weighted ties, what re-running routing does and does not disturb, and the
lifecycle consequence that voiding evidence unwinds an automatic decision.
"""

import json

import pytest
from sqlalchemy import select

from app.models import Annotator, FinalLabel, Label, Template, Unit, User, Webhook
from app.services.assignment import next_task, submit_label, void_unit
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.judges import attach_judge, create_judge_config, run_judge
from app.services.merge import (
    ReviewError,
    decide,
    effective_pipeline,
    final_label_for,
    merge_unit,
    merge_weight,
    queue_depth,
    review_item,
    review_queue,
    route_unit,
    validate_pipeline,
)
from app.services.merge.pipeline import PipelineError
from app.services.projects import create_project
from app.services.quality.reputation import gold_accuracy
from app.services.templates.seed import seed_templates
from app.services.webhooks import SendResult, set_default_sender

# --- helpers ----------------------------------------------------------------


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


def _rows(n, *, gold=None, golds=None):
    """``gold`` pins every unit's expected answer; ``golds`` gives one per unit."""
    rows = []
    for i in range(n):
        row = {"payload": {"image_url": f"http://x/{i}.png"}}
        expected = golds[i] if golds is not None else gold
        if expected is not None:
            row["is_gold"] = True
            row["gold_expected"] = {"category": expected}
        rows.append(json.dumps(row))
    return rows


def _ingest(db, project, rows):
    return ingest_units(db, project, parse_jsonl("\n".join(rows)))


def _submit(db, annotator, project, raw, **kwargs):
    slot = next_task(db, annotator.id, project.id)
    assert slot is not None, "expected an open slot"
    return submit_label(db, slot.id, annotator.id, raw=raw, **kwargs)


def _judge(db, project, name, answer):
    """A judge that always answers ``answer`` — a synthetic rater of known accuracy."""
    config = create_judge_config(
        db,
        name=name,
        provider="mock",
        model_id="mock-1",
        params={"mock": {"answers": {"category": answer}}},
    )
    attach_judge(db, project.id, config.id)
    return config


def _run(db, project, config, limit=8):
    """Run a judge, letting the orchestrator build the provider from the config —
    the pinned answers live in ``params``, so injecting a bare provider would
    quietly discard them and the judge would answer by prompt hash instead."""
    return run_judge(db, project.id, config.id, limit=limit)


class _Recorder:
    """A webhook sender that records instead of sending."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, url, body, headers):
        self.calls.append((url, body, headers))
        return SendResult(True, status_code=200)

    def events(self):
        return [json.loads(body)["event"] for _, body, _ in self.calls]


@pytest.fixture()
def recorder():
    """Install the recorder as the process-wide sender for one test.

    Registering it as the *default* rather than passing it in is deliberate: the
    events under test fire from deep inside the ordinary submit path, and a test
    that had to hand a sender down to them would be testing a different code path
    from the one production runs.
    """
    rec = _Recorder()
    set_default_sender(rec)
    try:
        yield rec
    finally:
        set_default_sender(None)


# --- acceptance #1: weights converge on known accuracies ---------------------


def test_synthetic_judges_with_known_accuracies_converge_to_merge_weights(db):
    """M8 acceptance #1 (§12). Two judges of *known, different* accuracy on a
    project of golds: one right on 6 of 8, one right on 2 of 8. Gold accuracy is
    what §6.2 calls reputation and §7.2 calls merge weight — the same number — so
    after a run the weights must order the judges by their true accuracy, and the
    merge must follow the calibrated one even when the vote count is tied.

    The pause threshold is switched off for this project on purpose: §6.1's
    cliff would remove the weaker judge entirely (which it does, and which
    ``test_a_judge_below_the_gold_threshold_is_removed_not_downweighted``
    asserts), and what is under test here is the *gradient* below that cliff.
    """
    expected = ["cat"] * 6 + ["dog"] * 2
    project = _project(
        db,
        "converge",
        labels_per_unit=2,
        max_labels_per_unit=2,
        gold_ratio=1.0,
        config={"quality": {"gold_threshold": 0.0}},
    )
    _ingest(db, project, _rows(8, golds=expected))

    good = _judge(db, project, "mostly-right", "cat")  # 6/8 = 0.75
    weak = _judge(db, project, "mostly-wrong", "dog")  # 2/8 = 0.25
    for config in (good, weak):
        assert _run(db, project, config).labels_written == 8

    good_ann = db.scalar(select(Annotator).where(Annotator.judge_config_id == good.id))
    weak_ann = db.scalar(select(Annotator).where(Annotator.judge_config_id == weak.id))
    assert gold_accuracy(db, good_ann.id) == (6, 8)
    assert gold_accuracy(db, weak_ann.id) == (2, 8)
    db.refresh(good_ann)
    db.refresh(weak_ann)

    # Reputation *is* the merge weight (§6.2 last line) — not a parallel score.
    assert merge_weight(good_ann) == max(0.05, min(1.0, good_ann.reputation_score))
    assert merge_weight(weak_ann) == max(0.05, min(1.0, weak_ann.reputation_score))

    # Converged in the direction the accuracies dictate, and separated clearly.
    assert merge_weight(good_ann) > merge_weight(weak_ann)
    assert merge_weight(good_ann) - merge_weight(weak_ann) > 0.2

    # And the consequence that makes the weights worth computing: on a 1-1 tie,
    # the better-calibrated judge decides.
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id).order_by(Unit.id))
    merged = merge_unit(db, unit, project)
    assert merged is not None
    assert merged.value == {"category": "cat"}
    assert merged.voter_count == 2
    assert merged.judge_votes == 2
    assert 0.5 < merged.confidence < 1.0, "a weighted win, not a unanimous one"

    provenance = merged.provenance()
    weights = {v["judge"]: v["weight"] for v in provenance["votes"]}
    assert weights["mostly-right"] > weights["mostly-wrong"]
    # §7.2: "who voted what, at which weight, in which variant".
    recorded = {"annotator_id", "weight", "variant", "value"}
    assert all(recorded <= set(vote) for vote in provenance["votes"])


def test_a_judge_below_the_gold_threshold_is_removed_not_downweighted(db):
    """The other half of the same story: below §6.1's threshold a judge is paused
    and its work voided, so it stops voting at all. Down-weighting is for the
    merely mediocre; the incompetent are shown the door — and because a judge is
    an annotator (principle 2), that happens with no judge-specific code."""
    project = _project(db, "cliff", labels_per_unit=1, max_labels_per_unit=1, gold_ratio=1.0)
    _ingest(db, project, _rows(6, gold="cat"))
    bad = _judge(db, project, "always-wrong", "dog")
    _run(db, project, bad, limit=6)

    bad_ann = db.scalar(select(Annotator).where(Annotator.judge_config_id == bad.id))
    assert bad_ann.status == "paused"
    assert bad_ann.pause_reason
    valid = list(db.scalars(select(Label).where(Label.annotator_id == bad_ann.id, Label.is_valid)))
    assert valid == [], "a paused rater's recent work is voided (§6.1)"


def test_a_majority_merge_ignores_weights_when_asked(db):
    """``merge: majority`` is the escape hatch for a project that does not want
    calibration to decide — one rater, one vote."""
    project = _project(db, "majority", labels_per_unit=2, max_labels_per_unit=2)
    _ingest(db, project, _rows(1))
    strong = _annotator(db, "strong@x.io")
    weak = _annotator(db, "weak@x.io")
    strong.reputation_score = 0.95
    weak.reputation_score = 0.10
    db.flush()

    _submit(db, strong, project, {"category": "cat"})
    _submit(db, weak, project, {"category": "dog"})
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))

    weighted = merge_unit(db, unit, project, method="calibration_weighted")
    assert weighted.value == {"category": "cat"}
    unweighted = merge_unit(db, unit, project, method="majority")
    # A true 1-1 tie under majority; the winner is deterministic but the *shares*
    # are equal, which is what stops it auto-finalizing.
    assert unweighted.confidence == 0.5


def test_the_ensemble_stage_can_restrict_itself_to_named_judges(db):
    """§7.2's ``"judges": [...]`` — humans present but not part of this ensemble."""
    project = _project(db, "named", labels_per_unit=2, max_labels_per_unit=2)
    _ingest(db, project, _rows(1))
    config = _judge(db, project, "picked-judge", "cat")
    _run(db, project, config, limit=1)
    human = _annotator(db, "human@x.io")
    _submit(db, human, project, {"category": "dog"})

    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    everyone = merge_unit(db, unit, project)
    assert everyone.voter_count == 2

    judges_only = merge_unit(db, unit, project, judges=["picked-judge"])
    assert judges_only.voter_count == 1
    assert judges_only.value == {"category": "cat"}
    assert judges_only.confidence == 1.0

    assert merge_unit(db, unit, project, judges=["a-judge-that-never-voted"]) is None


# --- auto-finalization (§7.2) ------------------------------------------------


def test_an_agreeing_unit_auto_finalizes_with_full_provenance(db):
    project = _project(db, "auto", labels_per_unit=2, max_labels_per_unit=2)
    _ingest(db, project, _rows(1))
    for i in range(2):
        _submit(db, _annotator(db, f"agree{i}@x.io"), project, {"category": "cat"})

    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    db.refresh(unit)
    assert unit.status == "finalized"
    assert unit.escalated_at is None

    final = final_label_for(db, unit.id)
    assert final is not None
    assert final.method == "auto_consensus"
    assert final.value == {"category": "cat"}
    assert final.confidence == 1.0
    assert final.provenance["stage"] == "auto_finalize"
    assert len(final.provenance["votes"]) == 2


def test_a_tolerance_rule_does_not_send_an_agreeing_unit_to_review(db):
    """A likert key declared ``within ±1`` must not be reported as maximally
    divergent by the entropy the default pipeline gates on — that would escalate
    units the project has explicitly said are in agreement (§6.4)."""
    project = _project(
        db,
        "tolerant",
        template="text-sentiment",
        labels_per_unit=2,
        max_labels_per_unit=2,
        agreement={
            "sentiment": {"match": "exact", "min_consensus": 0.5},
            "confidence": {"match": "within", "tolerance": 1, "min_consensus": 0.9},
        },
    )
    _ingest(db, project, ['{"payload": {"text": "hello"}}'])
    for i, confidence in enumerate((4, 5)):
        _submit(
            db,
            _annotator(db, f"tol{i}@x.io"),
            project,
            {"sentiment": "positive", "confidence": confidence},
        )

    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    db.refresh(unit)
    assert unit.escalated_at is None
    assert unit.status == "finalized"
    merged = merge_unit(db, unit, project)
    assert merged.entropy == 0.0, "±1 apart is one answer under this key's rule"


def test_a_unit_still_collecting_is_not_routed(db):
    """Merging mid-collection would finalize an answer we are still gathering."""
    project = _project(db, "partial", labels_per_unit=3, max_labels_per_unit=3)
    _ingest(db, project, _rows(1))
    _submit(db, _annotator(db, "one@x.io"), project, {"category": "cat"})

    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    db.refresh(unit)
    assert unit.status == "in_progress"
    assert final_label_for(db, unit.id) is None


# --- acceptance #2: disagreement routes to review, override is recorded ------


def test_a_disagreeing_unit_routes_to_review_and_an_override_is_recorded(db):
    """M8 acceptance #2 (§12). The disagreement escalates, the queue shows the
    merged proposal *and* every vote behind it, and the reviewer's override lands
    in ``final_labels`` with the provenance to explain it later."""
    project = _project(
        db,
        "escalate",
        labels_per_unit=2,
        max_labels_per_unit=2,
        agreement={"category": {"match": "exact", "min_consensus": 0.9}},
    )
    _ingest(db, project, _rows(1))
    _submit(db, _annotator(db, "cat@x.io"), project, {"category": "cat"})
    _submit(db, _annotator(db, "dog@x.io"), project, {"category": "dog"})

    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    db.refresh(unit)
    assert unit.escalated_at is not None
    assert unit.status != "finalized"
    assert queue_depth(db, project.id) == 1

    # The queue item carries what a reviewer needs to decide without a second view.
    queue = review_queue(db, project_id=project.id)
    assert queue["depth"] == 1
    item = queue["items"][0]
    assert item["unit_id"] == unit.id
    assert item["payload"]["image_url"].startswith("http://")
    assert item["proposal"] is not None
    assert {v["value"]["category"] for v in item["proposal"]["votes"]} == {"cat", "dog"}
    assert item["escalation_reason"]

    detail = review_item(db, unit.id)
    assert detail["template"]["schema"]["inputs"]  # enough to render answer widgets

    reviewer = User(email="rev@x.io", role="reviewer")
    db.add(reviewer)
    db.flush()
    outcome = decide(
        db,
        unit.id,
        decision="override",
        user_id=reviewer.id,
        value={"category": "bird"},
        comment="both raters misread the image",
    )

    assert outcome["method"] == "human_override"
    assert outcome["queue_depth"] == 0
    final = final_label_for(db, unit.id)
    assert final.value == {"category": "bird"}
    assert final.method == "human_override"
    assert final.decided_by == reviewer.id
    assert final.provenance["comment"] == "both raters misread the image"
    # The rejected proposal is kept: an override stays explainable a year later.
    assert final.provenance["proposal"]["votes"]
    assert {v["value"]["category"] for v in final.provenance["proposal"]["votes"]} == {"cat", "dog"}

    db.refresh(unit)
    assert unit.status == "finalized"
    assert unit.escalated_at is None
    assert queue_depth(db, project.id) == 0


def test_approving_takes_the_proposal_as_it_stands(db):
    project = _project(
        db,
        "approve",
        labels_per_unit=2,
        max_labels_per_unit=2,
        agreement={"category": {"match": "exact", "min_consensus": 0.99}},
    )
    _ingest(db, project, _rows(1))
    strong = _annotator(db, "strong@x.io")
    strong.reputation_score = 0.9
    db.flush()
    _submit(db, strong, project, {"category": "cat"})
    _submit(db, _annotator(db, "other@x.io"), project, {"category": "dog"})

    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    proposal = merge_unit(db, unit, project)
    outcome = decide(db, unit.id, decision="approve", user_id=None)

    assert outcome["method"] == "human_approved"
    assert outcome["value"] == proposal.value == {"category": "cat"}


def test_approving_a_unit_with_nothing_to_merge_is_refused(db):
    """Better a 409 than a finalized empty label."""
    project = _project(db, "nothing", labels_per_unit=1)
    _ingest(db, project, _rows(1))
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    try:
        decide(db, unit.id, decision="approve")
    except ReviewError as e:
        assert e.status == 409
    else:  # pragma: no cover - the assertion is that we got here
        raise AssertionError("approving with no labels must be refused")


def test_a_human_decision_is_never_overwritten_by_a_later_automatic_pass(db):
    """Re-running routing must not undo a reviewer. This is the property that
    makes ``POST /projects/{id}/route`` safe to press twice."""
    project = _project(
        db,
        "sticky",
        labels_per_unit=2,
        max_labels_per_unit=2,
        agreement={"category": {"match": "exact", "min_consensus": 0.9}},
    )
    _ingest(db, project, _rows(1))
    _submit(db, _annotator(db, "a@x.io"), project, {"category": "cat"})
    _submit(db, _annotator(db, "b@x.io"), project, {"category": "dog"})
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    decide(db, unit.id, decision="override", value={"category": "bird"})

    result = route_unit(db, unit, project)
    assert result.decision == "skipped"
    assert final_label_for(db, unit.id).value == {"category": "bird"}


def test_voiding_the_evidence_unwinds_an_automatic_decision(db):
    """An auto-finalized unit whose labels are voided must go back to collecting;
    leaving it finalized would keep a decision made from nothing."""
    project = _project(db, "unwind", labels_per_unit=2, max_labels_per_unit=2)
    _ingest(db, project, _rows(1))
    for i in range(2):
        _submit(db, _annotator(db, f"v{i}@x.io"), project, {"category": "cat"})
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    assert final_label_for(db, unit.id) is not None

    void_unit(db, unit.id)
    db.refresh(unit)
    assert unit.status == "pending"
    assert final_label_for(db, unit.id) is None


def test_voiding_does_not_unwind_a_human_decision(db):
    """A reviewer's verdict is not evidence that can be withdrawn by
    discrediting the raters underneath it."""
    project = _project(db, "human-sticky", labels_per_unit=2, max_labels_per_unit=2)
    _ingest(db, project, _rows(1))
    for i in range(2):
        _submit(db, _annotator(db, f"h{i}@x.io"), project, {"category": "cat"})
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    decide(db, unit.id, decision="override", value={"category": "bird"})

    void_unit(db, unit.id)
    final = final_label_for(db, unit.id)
    assert final is not None
    assert final.value == {"category": "bird"}


# --- acceptance #3: the backlog webhook --------------------------------------


def test_the_backlog_webhook_fires_past_its_threshold(db, recorder):
    """M8 acceptance #3 (§12, §7.3). No new trigger logic: the event fires off the
    escalation depth §7.2 already maintains, on the escalation that crosses the
    configured threshold — and it fires from the ordinary submit path, with no
    caller having to remember to check."""
    project = _project(
        db,
        "backlog",
        labels_per_unit=2,
        max_labels_per_unit=2,
        agreement={"category": {"match": "exact", "min_consensus": 0.9}},
        config={"review": {"backlog_threshold": 3}},
    )
    db.add(
        Webhook(
            event="review.queue_backlog",
            target_url="https://example.test/backlog",
            secret="s3cret",
            project_id=project.id,
        )
    )
    db.flush()
    _ingest(db, project, _rows(4))

    cats = [_annotator(db, f"cat{i}@x.io") for i in range(4)]
    dogs = [_annotator(db, f"dog{i}@x.io") for i in range(4)]
    depth_when_fired = []
    for i in range(4):
        _submit(db, cats[i], project, {"category": "cat"})
        _submit(db, dogs[i], project, {"category": "dog"})
        if len(recorder.calls) > len(depth_when_fired):
            depth_when_fired.append(queue_depth(db, project.id))

    assert queue_depth(db, project.id) == 4
    # Fired once, on the escalation that made the depth equal the threshold —
    # not on every escalation past it.
    assert recorder.events() == ["review.queue_backlog"]
    assert depth_when_fired == [3]

    url, body, headers = recorder.calls[0]
    payload = json.loads(body)
    assert url == "https://example.test/backlog"
    assert payload["project_id"] == project.id
    assert payload["metric"] == {"queue_depth": 3, "threshold": 3}
    assert headers["X-MiniLP-Signature"].startswith("sha256=")

    # Drain one and let the backlog re-form: a backlog that came back is news.
    unit = db.scalars(
        select(Unit).where(Unit.project_id == project.id, Unit.escalated_at.is_not(None))
    ).first()
    decide(db, unit.id, decision="override", value={"category": "bird"})
    assert queue_depth(db, project.id) == 3
    assert recorder.events() == ["review.queue_backlog"]


def test_project_completed_fires_once_when_the_last_unit_finalizes(db, recorder):
    project = _project(db, "completed", labels_per_unit=1, max_labels_per_unit=1)
    db.add(
        Webhook(
            event="project.completed",
            target_url="https://example.test/done",
            project_id=project.id,
        )
    )
    db.flush()
    _ingest(db, project, _rows(2))

    _submit(db, _annotator(db, "f1@x.io"), project, {"category": "cat"})
    assert recorder.events() == []  # one unit left

    _submit(db, _annotator(db, "f2@x.io"), project, {"category": "cat"})
    assert recorder.events() == ["project.completed"]

    # Announced once: a completed project does not keep announcing itself.
    from app.services.merge.finalize import check_project_completed

    assert check_project_completed(db, project) == 0
    assert recorder.events() == ["project.completed"]


# --- the pipeline document ---------------------------------------------------


def test_a_project_with_no_pipeline_gets_the_shipped_default(db):
    project = _project(db, "default-pipeline", labels_per_unit=1)
    stages = [s["stage"] for s in effective_pipeline(project)]
    assert stages == ["ensemble", "auto_finalize", "human_review"]


def test_a_custom_pipeline_changes_where_units_go(db):
    """The same two agreeing labels, auto-finalized under the default and sent to
    review under a stricter threshold — the pipeline is genuinely the policy."""
    project = _project(
        db,
        "strict",
        labels_per_unit=2,
        max_labels_per_unit=2,
        pipeline=[
            {"stage": "ensemble", "merge": "calibration_weighted"},
            {"stage": "auto_finalize", "if": "consensus >= 0.9 && votes >= 5"},
            {"stage": "human_review", "else": True},
        ],
    )
    _ingest(db, project, _rows(1))
    for i in range(2):
        _submit(db, _annotator(db, f"s{i}@x.io"), project, {"category": "cat"})

    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    db.refresh(unit)
    assert unit.escalated_at is not None
    assert final_label_for(db, unit.id) is None


def test_an_invalid_pipeline_is_refused_at_save_time(db):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == "image-classification"))
    for bad in (
        [{"stage": "teleport"}],
        [{"stage": "auto_finalize", "if": "consensuss >= 0.9"}],
        [{"stage": "ensemble", "merge": "vibes"}],
        [{"stage": "ensemble", "judges": "not-a-list"}],
        [{"no_stage_key": 1}],
    ):
        try:
            validate_pipeline(bad)
        except PipelineError:
            continue
        raise AssertionError(f"expected {bad} to be refused")

    try:
        create_project(db, name="bad", template_id=tmpl.id, pipeline=[{"stage": "nope"}])
    except Exception as e:
        assert "nope" in str(e)
    else:  # pragma: no cover
        raise AssertionError("create_project must validate the pipeline")


def test_routing_writes_one_final_label_per_unit_however_often_it_runs(db):
    project = _project(db, "idempotent", labels_per_unit=1, max_labels_per_unit=1)
    _ingest(db, project, _rows(1))
    _submit(db, _annotator(db, "once@x.io"), project, {"category": "cat"})
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))

    for _ in range(3):
        route_unit(db, unit, project)

    rows = list(db.scalars(select(FinalLabel).where(FinalLabel.unit_id == unit.id)))
    assert len(rows) == 1
