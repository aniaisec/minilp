"""Quality pipeline end-to-end against real PostgreSQL (M4 acceptance, §6).

The three acceptance criteria from §12 M4 have a test each, named after them:

- ``test_below_threshold_gold_accuracy_pauses_and_voids_with_balance_preserved``
- ``test_disagreeing_unit_grows_to_max_then_escalates``
- (kappa fixtures live in ``test_quality_agreement.py``, which needs no DB)

plus the surrounding behavior: server-side canonicalization, reputation
components, and ``min_reputation`` assignment gating.
"""

from sqlalchemy import select

from app.models import Annotator, Label, ReputationEvent, Slot, Template, Unit, User
from app.services.assignment import AssignmentError, next_task, submit_label
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.quality import (
    compute_reputation,
    gold_accuracy,
    peer_agreement,
    resume_annotator,
    variant_bias,
)
from app.services.slots.generation import verify_balance
from app.services.templates.seed import seed_templates

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
    return create_project(db, name=name, template_id=tmpl.id, **kwargs)


def _ingest(db, project, lines):
    return ingest_units(db, project, parse_jsonl("\n".join(lines)))


def _image_unit(category=None, priority=0):
    row = {"payload": {"image_url": "http://x/1.png"}, "priority": priority}
    if category is not None:
        row["is_gold"] = True
        row["gold_expected"] = {"category": category}
    return __import__("json").dumps(row)


def _lease_and_submit(db, annotator, project, raw, **kwargs):
    slot = next_task(db, annotator.id, project.id)
    assert slot is not None, "expected an open slot"
    return submit_label(db, slot.id, annotator.id, raw=raw, **kwargs)


# --- canonicalization is server-side (§2.6) ---------------------------------


def test_server_recanonicalizes_and_ignores_a_wrong_client_value(db):
    """The client's ``value`` is advisory: a lying client cannot poison analytics."""
    project = _project(db, "canon", labels_per_unit=1, gold_ratio=0.0)
    _ingest(db, project, [_image_unit()])
    ann = _annotator(db, "canon@x.io")

    label = _lease_and_submit(
        db, ann, project, {"category": "other:capybara"}, value={"category": "TOTALLY_WRONG"}
    )
    assert label.value == {"category": "capybara"}
    assert label.raw == {"category": "other:capybara"}


def test_positional_choice_canonicalizes_through_the_slot_variant(db):
    """Side-by-side: raw keeps the side clicked, value keeps the item (§9)."""
    project = _project(
        db, "sbs", template="side-by-side-preference", labels_per_unit=2, gold_ratio=0.0
    )
    _ingest(
        db,
        project,
        ['{"payload": {"prompt": "p", "response_a": "a", "response_b": "b"}}'],
    )
    ann = _annotator(db, "sbs@x.io")

    slot = next_task(db, ann.id, project.id)
    label = submit_label(db, slot.id, ann.id, raw={"choice": "Left"})
    expected = slot.variant["panel_order"][0]
    assert label.value == {"choice": expected}


# --- gold grading + reputation (§6.1, §6.2) ---------------------------------


def test_correct_gold_records_a_pass_event_and_marks_the_label(db):
    project = _project(db, "gold-pass", labels_per_unit=1, gold_ratio=1.0)
    _ingest(db, project, [_image_unit(category="cat")])
    ann = _annotator(db, "pass@x.io")

    label = _lease_and_submit(db, ann, project, {"category": "cat"})
    assert label.gold_passed is True
    kinds = list(
        db.scalars(select(ReputationEvent.kind).where(ReputationEvent.annotator_id == ann.id))
    )
    assert "gold_pass" in kinds


def test_wrong_gold_records_a_fail_event(db):
    project = _project(db, "gold-fail", labels_per_unit=1, gold_ratio=1.0)
    _ingest(db, project, [_image_unit(category="cat")])
    ann = _annotator(db, "fail@x.io")

    label = _lease_and_submit(db, ann, project, {"category": "dog"})
    assert label.gold_passed is False
    kinds = list(
        db.scalars(select(ReputationEvent.kind).where(ReputationEvent.annotator_id == ann.id))
    )
    assert "gold_fail" in kinds


def test_non_gold_labels_are_not_graded(db):
    project = _project(db, "no-gold", labels_per_unit=1, gold_ratio=0.0)
    _ingest(db, project, [_image_unit()])
    ann = _annotator(db, "nogold@x.io")

    label = _lease_and_submit(db, ann, project, {"category": "cat"})
    assert label.gold_passed is None


def test_rolling_gold_accuracy_counts_only_the_window(db):
    project = _project(
        db,
        "window",
        labels_per_unit=1,
        gold_ratio=1.0,
        config={"quality": {"gold_window": 2, "gold_min_samples": 99}},
    )
    _ingest(db, project, [_image_unit(category="cat") for _ in range(4)])
    ann = _annotator(db, "window@x.io")

    for answer in ("dog", "dog", "cat", "cat"):  # two wrong, then two right
        _lease_and_submit(db, ann, project, {"category": answer})

    passes, total = gold_accuracy(db, ann.id, project_id=project.id, window=2)
    assert (passes, total) == (2, 2)  # the window sees only the recent two
    passes_all, total_all = gold_accuracy(db, ann.id, project_id=project.id, window=10)
    assert (passes_all, total_all) == (2, 4)


def test_a_speed_flag_is_recorded_for_an_implausibly_fast_human(db):
    project = _project(db, "speed", labels_per_unit=1, gold_ratio=0.0)
    _ingest(db, project, [_image_unit()])
    ann = _annotator(db, "speed@x.io")

    _lease_and_submit(db, ann, project, {"category": "cat"}, latency_ms=50)
    flags = list(
        db.scalars(
            select(ReputationEvent.id).where(
                ReputationEvent.annotator_id == ann.id,
                ReputationEvent.kind == "speed_flag",
            )
        )
    )
    assert len(flags) == 1


def test_a_model_judge_is_not_speed_flagged(db):
    """A judge answering in 200ms is expected, not suspicious (§6.2)."""
    from app.models import JudgeConfig

    project = _project(db, "judge-speed", labels_per_unit=1, gold_ratio=0.0)
    _ingest(db, project, [_image_unit()])
    config = JudgeConfig(name="j", provider="mock", model_id="m")
    db.add(config)
    db.flush()
    judge = Annotator(kind="model", judge_config_id=config.id, display_name="judge")
    db.add(judge)
    db.flush()

    _lease_and_submit(db, judge, project, {"category": "cat"}, latency_ms=10)
    assert (
        db.scalar(
            select(ReputationEvent.id).where(
                ReputationEvent.annotator_id == judge.id,
                ReputationEvent.kind == "speed_flag",
            )
        )
        is None
    )


# --- M4 acceptance: pausing voids recent work, balance preserved ------------


def test_below_threshold_gold_accuracy_pauses_and_voids_with_balance_preserved(db):
    """M4 acceptance criterion #1.

    A variant-bearing project (K=2, values AB/BA) so the balance claim is
    meaningful: after the pause the unit's slots must still be exactly one AB and
    one BA, all back in the open pool.
    """
    project = _project(
        db,
        "pause-me",
        template="side-by-side-preference",
        labels_per_unit=2,
        max_labels_per_unit=2,
        gold_ratio=1.0,
        config={"quality": {"gold_threshold": 0.7, "gold_window": 5, "gold_min_samples": 3}},
    )
    gold_row = (
        '{"payload": {"prompt": "p", "response_a": "a", "response_b": "b"}, '
        '"is_gold": true, "gold_expected": {"choice": "A"}}'
    )
    _ingest(db, project, [gold_row for _ in range(4)])
    ann = _annotator(db, "sloppy@x.io")

    # Answer three golds; deliberately pick the item that is *not* A each time.
    for _ in range(3):
        slot = next_task(db, ann.id, project.id)
        assert slot is not None
        order = slot.variant["panel_order"]
        wrong_side = "Left" if order[0] == "B" else "Right"
        submit_label(db, slot.id, ann.id, raw={"choice": wrong_side})

    db.refresh(ann)
    assert ann.status == "paused"
    assert ann.pause_reason and "gold accuracy" in ann.pause_reason

    # Their work is voided (audit trail kept) ...
    labels = list(db.scalars(select(Label).where(Label.annotator_id == ann.id)))
    assert labels and all(not label.is_valid for label in labels)

    # ... and every touched unit is back to a balanced, fully open slot pool.
    template = db.get(Template, project.template_id)
    for unit_id in {label.unit_id for label in labels}:
        slots = list(db.scalars(select(Slot).where(Slot.unit_id == unit_id)))
        assert all(s.status == "open" for s in slots)
        assert verify_balance([s.variant for s in slots], template.schema)

    # And they can no longer be assigned work.
    try:
        next_task(db, ann.id, project.id)
    except AssignmentError as e:
        assert e.status == 403
    else:
        raise AssertionError("a paused annotator must not be assigned work")


def test_one_bad_gold_does_not_pause_below_min_samples(db):
    """Nobody is suspended on a single unlucky answer (§6.1 gold_min_samples)."""
    project = _project(
        db,
        "patient",
        labels_per_unit=1,
        gold_ratio=1.0,
        config={"quality": {"gold_threshold": 0.9, "gold_min_samples": 5}},
    )
    _ingest(db, project, [_image_unit(category="cat") for _ in range(3)])
    ann = _annotator(db, "unlucky@x.io")

    _lease_and_submit(db, ann, project, {"category": "dog"})
    db.refresh(ann)
    assert ann.status == "active"


def test_resume_reactivates_without_unvoiding(db):
    project = _project(
        db,
        "resume",
        labels_per_unit=1,
        gold_ratio=1.0,
        config={"quality": {"gold_threshold": 0.9, "gold_min_samples": 2}},
    )
    _ingest(db, project, [_image_unit(category="cat") for _ in range(3)])
    ann = _annotator(db, "resume@x.io")
    for _ in range(2):
        _lease_and_submit(db, ann, project, {"category": "dog"})

    db.refresh(ann)
    assert ann.status == "paused"
    resume_annotator(db, ann.id)
    db.refresh(ann)
    assert ann.status == "active" and ann.pause_reason is None
    assert all(
        not label.is_valid
        for label in db.scalars(select(Label).where(Label.annotator_id == ann.id))
    )


# --- M4 acceptance: growth then escalation (§6.4) ---------------------------


def test_disagreeing_unit_grows_to_max_then_escalates(db):
    """M4 acceptance criterion #2.

    K=2, max=4, ``grow_then_escalate``. Four annotators give answers that never
    reach a 0.9 consensus, so after the 2nd and 3rd labels the unit grows by one
    slot each time; at 4 slots it is capped and must escalate rather than grow
    forever.

    (K=1 would prove nothing: a lone vote is trivially unanimous.)
    """
    project = _project(
        db,
        "grow",
        labels_per_unit=2,
        max_labels_per_unit=4,
        gold_ratio=0.0,
        agreement={"category": {"match": "exact", "min_consensus": 0.9}},
        config={"quality": {"on_disagreement": "grow_then_escalate"}},
    )
    _ingest(db, project, [_image_unit()])
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    expected_slots = [2, 3, 4, 4]  # after each submission

    for i, answer in enumerate(("cat", "dog", "bird", "cat")):
        ann = _annotator(db, f"grower{i}@x.io")
        _lease_and_submit(db, ann, project, {"category": answer})
        db.refresh(unit)
        slots = list(db.scalars(select(Slot).where(Slot.unit_id == unit.id)))
        assert len(slots) == expected_slots[i], f"after label {i + 1}"
        if i < 3:
            assert unit.escalated_at is None, f"escalated too early (label {i + 1})"

    assert unit.escalated_at is not None
    assert unit.quality["action"] == "escalated"
    assert unit.quality["failed_keys"] == ["category"]


def test_growth_adds_a_whole_balanced_round_for_variant_templates(db):
    """Growth is n slots at a time so K/n balance can still hold (§2.7)."""
    project = _project(
        db,
        "grow-balanced",
        template="side-by-side-preference",
        labels_per_unit=2,
        max_labels_per_unit=4,
        gold_ratio=0.0,
        agreement={"choice": {"match": "exact", "min_consensus": 0.99}},
    )
    _ingest(
        db,
        project,
        ['{"payload": {"prompt": "p", "response_a": "a", "response_b": "b"}}'],
    )
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))
    template = db.get(Template, project.template_id)

    # Two annotators disagree on the item (not merely the side).
    for i, side in enumerate(("Left", "Right")):
        ann = _annotator(db, f"bal{i}@x.io")
        slot = next_task(db, ann.id, project.id)
        order = slot.variant["panel_order"]
        pick = side if order == "AB" else ("Right" if side == "Left" else "Left")
        submit_label(db, slot.id, ann.id, raw={"choice": pick})

    slots = list(db.scalars(select(Slot).where(Slot.unit_id == unit.id)))
    assert len(slots) == 4  # grew by a full round of 2
    assert verify_balance([s.variant for s in slots], template.schema)


def test_agreeing_unit_neither_grows_nor_escalates(db):
    project = _project(
        db,
        "agree",
        labels_per_unit=2,
        max_labels_per_unit=4,
        gold_ratio=0.0,
        agreement={"category": {"match": "exact", "min_consensus": 0.9}},
    )
    _ingest(db, project, [_image_unit()])
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))

    for i in range(2):
        ann = _annotator(db, f"agreer{i}@x.io")
        _lease_and_submit(db, ann, project, {"category": "cat"})

    db.refresh(unit)
    assert len(list(db.scalars(select(Slot).where(Slot.unit_id == unit.id)))) == 2
    assert unit.escalated_at is None
    assert unit.quality["action"] == "agreed"
    assert unit.status == "labeled"


def test_escalate_policy_skips_growth_entirely(db):
    project = _project(
        db,
        "straight-escalate",
        labels_per_unit=2,
        max_labels_per_unit=6,
        gold_ratio=0.0,
        agreement={"category": {"match": "exact", "min_consensus": 0.9}},
        config={"quality": {"on_disagreement": "escalate"}},
    )
    _ingest(db, project, [_image_unit()])
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))

    for i, answer in enumerate(("cat", "dog")):
        ann = _annotator(db, f"esc{i}@x.io")
        _lease_and_submit(db, ann, project, {"category": answer})

    db.refresh(unit)
    assert len(list(db.scalars(select(Slot).where(Slot.unit_id == unit.id)))) == 2
    assert unit.escalated_at is not None
    assert unit.quality["action"] == "escalated"


def test_tolerance_policy_prevents_a_needless_escalation(db):
    """Likert ±1: 4 and 5 are consensus, so the unit must not escalate (§6.4)."""
    project = _project(
        db,
        "tolerant",
        template="text-sentiment",
        labels_per_unit=2,
        max_labels_per_unit=4,
        gold_ratio=0.0,
        agreement={
            "sentiment": {"match": "exact", "min_consensus": 0.5},
            "confidence": {"match": "within", "tolerance": 1, "min_consensus": 0.9},
        },
    )
    _ingest(db, project, ['{"payload": {"text": "hello"}}'])
    unit = db.scalar(select(Unit).where(Unit.project_id == project.id))

    for i, confidence in enumerate((4, 5)):
        ann = _annotator(db, f"tol{i}@x.io")
        _lease_and_submit(db, ann, project, {"sentiment": "positive", "confidence": confidence})

    db.refresh(unit)
    assert unit.escalated_at is None
    assert unit.quality["action"] == "agreed"


# --- reputation components (§6.2) -------------------------------------------


def test_peer_agreement_counts_matching_the_majority(db):
    project = _project(db, "peers", labels_per_unit=3, max_labels_per_unit=3, gold_ratio=0.0)
    _ingest(db, project, [_image_unit()])

    conformist = _annotator(db, "conformist@x.io")
    other = _annotator(db, "other@x.io")
    contrarian = _annotator(db, "contrarian@x.io")
    _lease_and_submit(db, conformist, project, {"category": "cat"})
    _lease_and_submit(db, other, project, {"category": "cat"})
    _lease_and_submit(db, contrarian, project, {"category": "dog"})

    assert peer_agreement(db, conformist.id, project_id=project.id) == (1, 1)
    assert peer_agreement(db, contrarian.id, project_id=project.id) == (0, 1)


def test_variant_bias_measures_the_left_right_split(db):
    project = _project(
        db,
        "bias",
        template="side-by-side-preference",
        labels_per_unit=2,
        gold_ratio=0.0,
    )
    rows = [
        f'{{"payload": {{"prompt": "p{i}", "response_a": "a", "response_b": "b"}}}}'
        for i in range(4)
    ]
    _ingest(db, project, rows)
    lefty = _annotator(db, "lefty@x.io")

    for _ in range(4):
        _lease_and_submit(db, lefty, project, {"choice": "Left"})

    bias, n = variant_bias(db, lefty.id, project_id=project.id)
    assert n == 4
    assert bias == 1.0  # always the same side


def test_reputation_starts_high_for_a_new_annotator(db):
    """The §6.2 prior: nobody is locked out before answering their first gold."""
    ann = _annotator(db, "fresh@x.io")
    assert compute_reputation(db, ann.id).score >= 0.9


def test_reputation_falls_after_failed_golds(db):
    project = _project(
        db,
        "rep-drop",
        labels_per_unit=1,
        gold_ratio=1.0,
        config={"quality": {"gold_min_samples": 99}},  # measure, don't pause
    )
    _ingest(db, project, [_image_unit(category="cat") for _ in range(6)])
    ann = _annotator(db, "dropper@x.io")

    before = compute_reputation(db, ann.id, project_id=project.id).score
    for _ in range(6):
        _lease_and_submit(db, ann, project, {"category": "dog"})

    db.refresh(ann)
    after = compute_reputation(db, ann.id, project_id=project.id).score
    assert after < before
    assert ann.reputation_score == after  # the cached column tracks the live value


# --- assignment gating (§6.2) -----------------------------------------------


def test_min_reputation_gates_assignment(db):
    project = _project(
        db,
        "gated",
        labels_per_unit=1,
        gold_ratio=1.0,
        min_reputation=0.8,
        config={"quality": {"gold_min_samples": 99}},
    )
    _ingest(db, project, [_image_unit(category="cat") for _ in range(8)])
    ann = _annotator(db, "gated@x.io")

    # Eligible at first thanks to the §6.2 prior, despite having no history.
    first = next_task(db, ann.id, project.id)
    assert first is not None
    submit_label(db, first.id, ann.id, raw={"category": "dog"})

    # Keep failing golds until the gate closes.
    gated = None
    for _ in range(8):
        try:
            slot = next_task(db, ann.id, project.id, sweep=False)
        except AssignmentError as e:
            gated = e
            break
        if slot is None:
            break
        submit_label(db, slot.id, ann.id, raw={"category": "dog"})

    assert gated is not None, "expected a reputation gate"
    assert gated.status == 403
    assert "below the project minimum" in str(gated)


def test_min_reputation_zero_gates_nobody(db):
    project = _project(db, "ungated", labels_per_unit=1, gold_ratio=0.0, min_reputation=0.0)
    _ingest(db, project, [_image_unit()])
    ann = _annotator(db, "ungated@x.io")
    assert next_task(db, ann.id, project.id) is not None
