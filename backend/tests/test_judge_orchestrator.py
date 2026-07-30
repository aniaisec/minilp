"""M7 acceptance suite — the judge orchestrator against real PostgreSQL (§7.1).

§12's three acceptance criteria have a test each, named after them:

- ``test_mock_judge_fills_slots_respecting_variant_balance``
- ``test_a_judge_is_served_golds_and_is_graded_like_a_human``
- ``test_cache_prevents_duplicate_spend``
- ``test_budget_cap_hard_stops_and_fires_its_webhook``

plus the surrounding behavior: enrollment, dry-run, failure handling, prompt
versioning, and — the one that proves the design rather than the feature — that a
judge's labels are indistinguishable to every downstream subsystem.
"""

import json

import pytest
from sqlalchemy import select

from app.models import Annotator, JudgeCacheEntry, JudgeRun, Label, Slot, Template, Unit, Webhook
from app.services.assignment import void_unit
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.judges import (
    JudgeError,
    attach_judge,
    create_judge_config,
    detach_judge,
    dry_run_estimate,
    judge_spend,
    new_version,
    project_costs,
    run_judge,
)
from app.services.judges.providers import MockProvider, ProviderError
from app.services.projects import create_project
from app.services.slots.generation import verify_balance
from app.services.templates.seed import seed_templates
from app.services.webhooks import SendResult

# --- helpers ----------------------------------------------------------------


def _project(db, name, *, template="image-classification", **kwargs):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == template))
    kwargs.setdefault("gold_ratio", 0.0)
    return create_project(db, name=name, template_id=tmpl.id, **kwargs)


def _image_rows(n, *, gold_every=0, gold_answer="cat"):
    rows = []
    for i in range(n):
        row = {"payload": {"image_url": f"http://x/{i}.png"}}
        if gold_every and i % gold_every == 0:
            row["is_gold"] = True
            row["gold_expected"] = {"category": gold_answer}
        rows.append(json.dumps(row))
    return rows


def _pair_rows(n):
    return [
        json.dumps(
            {
                "payload": {
                    "prompt": f"question {i}",
                    "response_a": f"answer A{i}",
                    "response_b": f"answer B{i}",
                }
            }
        )
        for i in range(n)
    ]


def _ingest(db, project, rows):
    return ingest_units(db, project, parse_jsonl("\n".join(rows)))


def _judge(db, project, *, name="mock-judge", budget=None, params=None, prompt=None):
    config = create_judge_config(
        db,
        name=name,
        provider="mock",
        model_id="mock-1",
        params=params or {},
        prompt_template=prompt,
        budget=budget,
    )
    attach_judge(db, project.id, config.id)
    return config


class _Recorder:
    """A webhook sender that records instead of sending."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, url, body, headers):
        self.calls.append((url, body, headers))
        return SendResult(self.ok, status_code=200 if self.ok else 500, error=None)


# --- enrollment (§7.1) -------------------------------------------------------


def test_attaching_a_judge_creates_a_model_annotator(db):
    project = _project(db, "enroll")
    config = create_judge_config(db, name="j", provider="mock", model_id="mock-1")

    result = attach_judge(db, project.id, config.id)
    annotator = db.get(Annotator, result["annotator_id"])

    assert annotator.kind == "model"
    assert annotator.judge_config_id == config.id
    assert annotator.user_id is None, "a judge has no user — §4's CHECK depends on it"
    assert result["display_name"] == "j v1"


def test_attaching_twice_is_idempotent(db):
    """Otherwise the same judge would vote twice on every unit."""
    project = _project(db, "enroll2")
    config = create_judge_config(db, name="j", provider="mock", model_id="mock-1")
    first = attach_judge(db, project.id, config.id)
    second = attach_judge(db, project.id, config.id)

    assert first["annotator_id"] == second["annotator_id"]
    assert len(project.config["judges"]) == 1


def test_running_an_unattached_judge_is_refused(db):
    project = _project(db, "unattached")
    config = create_judge_config(db, name="j", provider="mock", model_id="mock-1")
    with pytest.raises(JudgeError) as e:
        run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))
    assert e.value.status == 409


def test_a_new_prompt_version_is_a_new_judge_with_its_own_annotator(db):
    """§4: immutable per prompt version. v2's labels must not land under v1."""
    project = _project(db, "versions")
    v1 = create_judge_config(db, name="j", provider="mock", model_id="mock-1", prompt_template="A")
    v2 = new_version(db, v1.id, prompt_template="B")

    assert (v1.prompt_version, v2.prompt_version) == (1, 2)
    assert v1.prompt_template == "A", "the old version must not be mutated"

    a1 = attach_judge(db, project.id, v1.id)["annotator_id"]
    a2 = attach_judge(db, project.id, v2.id)["annotator_id"]
    assert a1 != a2


def test_detaching_stops_new_work_but_keeps_existing_labels(db):
    project = _project(db, "detach", labels_per_unit=1)
    _ingest(db, project, _image_rows(2))
    config = _judge(db, project)
    run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))
    before = db.scalar(select(Label).where(Label.is_valid.is_(True)))
    assert before is not None

    detach_judge(db, project.id, config.id)
    assert db.get(Label, before.id).is_valid is True
    with pytest.raises(JudgeError):
        run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))


# --- acceptance: fills slots respecting balance and golds --------------------


def test_mock_judge_fills_slots_respecting_variant_balance(db):
    """M7 acceptance #1. The judge pulls through the ordinary assignment engine,
    so the §2.7 K/n invariant must survive a judge run untouched."""
    project = _project(db, "balance", template="side-by-side-preference", labels_per_unit=2)
    _ingest(db, project, _pair_rows(4))

    config = _judge(db, project)
    result = run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))

    # One annotator can only label a unit once (§2.7), so a single judge fills
    # exactly one of each unit's two variant slots — 4 labels, not 8.
    assert result.labels_written == 4
    assert result.stopped_reason == "exhausted"

    template = db.get(Template, project.template_id)
    for unit in db.scalars(select(Unit).where(Unit.project_id == project.id)):
        variants = [s.variant for s in db.scalars(select(Slot).where(Slot.unit_id == unit.id))]
        assert verify_balance(variants, template.schema), f"unit {unit.id} lost balance"

    # Exactly one slot per unit was consumed, and every remaining slot is still
    # open with its variant intact — the other half of each pair is waiting for a
    # second rater, which is what K=2 means.
    filled = db.scalars(
        select(Slot)
        .join(Unit, Slot.unit_id == Unit.id)
        .where(Unit.project_id == project.id, Slot.status == "filled")
    ).all()
    assert len(filled) == 4
    assert len({s.unit_id for s in filled}) == 4
    remaining = db.scalars(
        select(Slot)
        .join(Unit, Slot.unit_id == Unit.id)
        .where(Unit.project_id == project.id, Slot.status == "open")
    ).all()
    assert len(remaining) == 4
    assert all(s.variant and s.variant.get("panel_order") for s in remaining)


def test_two_judges_fill_both_variant_slots_of_every_unit(db):
    """Ensemble shape (the M8 precondition): K=2 filled by two different judges."""
    project = _project(db, "two", template="side-by-side-preference", labels_per_unit=2)
    _ingest(db, project, _pair_rows(3))
    a = _judge(db, project, name="judge-a")
    b = _judge(db, project, name="judge-b")

    run_judge(db, project.id, a.id, provider=MockProvider(model_id="m"))
    run_judge(db, project.id, b.id, provider=MockProvider(model_id="m"))

    for unit in db.scalars(select(Unit).where(Unit.project_id == project.id)):
        labels = db.scalars(
            select(Label).where(Label.unit_id == unit.id, Label.is_valid.is_(True))
        ).all()
        assert len(labels) == 2
        assert len({label.annotator_id for label in labels}) == 2
        assert unit.status in ("labeled", "finalized")


def test_a_judge_is_served_golds_and_is_graded_like_a_human(db):
    """M7 acceptance #1 (golds half). Gold injection, grading and the reputation
    event all come free from enrolling as an annotator — no judge branch anywhere."""
    project = _project(db, "golds", gold_ratio=0.5, labels_per_unit=1)
    _ingest(db, project, _image_rows(6, gold_every=2, gold_answer="cat"))

    # Pin the answer so the gold outcome is deterministic rather than a coin flip.
    config = _judge(db, project, params={"mock": {"answers": {"category": "cat"}}})
    run_judge(
        db,
        project.id,
        config.id,
        provider=MockProvider(model_id="m", params={"mock": {"answers": {"category": "cat"}}}),
    )

    graded = db.scalars(
        select(Label).join(Unit, Label.unit_id == Unit.id).where(Unit.is_gold.is_(True))
    ).all()
    assert graded, "the judge was never served a gold"
    assert all(label.gold_passed is True for label in graded)

    annotator = db.scalar(select(Annotator).where(Annotator.judge_config_id == config.id))
    assert annotator.reputation_score > 0.5, "gold passes must move the judge's reputation"


def test_a_judge_never_labels_the_same_unit_twice(db):
    """The §2.7 exclusion applies to judges — including across repeated runs."""
    project = _project(db, "exclusion", labels_per_unit=1)
    _ingest(db, project, _image_rows(3))
    config = _judge(db, project)

    first = run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))
    second = run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))

    assert first.labels_written == 3
    assert second.labels_written == 0
    assert second.stopped_reason == "exhausted"


def test_judge_labels_are_canonicalized_server_side_like_any_other(db):
    """A judge answers positionally ("Left"); the server maps it to the item (§2.8).

    This is what makes LLM order bias measurable at all — and it happens because
    the judge went through ``submit_label``, not because anything here asked."""
    project = _project(db, "canon", template="side-by-side-preference", labels_per_unit=2)
    _ingest(db, project, _pair_rows(2))
    config = _judge(db, project, params={"mock": {"answers": {"choice": "Left"}}})

    run_judge(
        db,
        project.id,
        config.id,
        provider=MockProvider(model_id="m", params={"mock": {"answers": {"choice": "Left"}}}),
    )

    for label in db.scalars(select(Label).where(Label.is_valid.is_(True))):
        slot = db.get(Slot, label.slot_id)
        assert label.raw["choice"] == "Left"
        assert label.value["choice"] == slot.variant["panel_order"][0]


def test_confidence_and_reasoning_are_captured(db):
    project = _project(db, "capture", labels_per_unit=1)
    _ingest(db, project, _image_rows(1))
    config = _judge(db, project)
    run_judge(
        db,
        project.id,
        config.id,
        provider=MockProvider(
            model_id="m", params={"mock": {"confidence": 0.83, "reasoning": "Because."}}
        ),
    )
    label = db.scalar(select(Label))
    assert label.confidence == pytest.approx(0.83)
    assert label.reasoning == "Because."
    assert label.tokens_in > 0 and label.latency_ms is not None


# --- acceptance: the cache ---------------------------------------------------


def test_cache_prevents_duplicate_spend(db):
    """M7 acceptance #2. Re-running the same judge over re-opened slots must read
    the cache, not the provider."""
    project = _project(db, "cache", labels_per_unit=1)
    _ingest(db, project, _image_rows(3))
    config = _judge(db, project, params={"price": {"input": 1000.0, "output": 1000.0}})

    first = run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))
    assert first.labels_written == 3
    assert first.cache_hits == 0
    assert first.cost_usd > 0
    assert db.scalar(select(JudgeCacheEntry).limit(1)) is not None

    # Void the labels so the same units come back around, then re-run. Goes
    # through the real void path rather than poking rows: since M8 a unit that
    # agreed is auto-finalized (§7.2), and only ``void_unit`` knows to unwind
    # that along with the labels.
    for unit_id in list(db.scalars(select(Unit.id).where(Unit.project_id == project.id))):
        void_unit(db, unit_id)
    db.flush()

    second = run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))
    assert second.labels_written == 3
    assert second.cache_hits == 3, "identical calls must never be paid for twice (§4)"
    assert second.cost_usd == 0.0
    assert all(
        label.cache_hit for label in db.scalars(select(Label).where(Label.is_valid.is_(True)))
    )


def test_the_cache_key_separates_variants(db):
    """The same unit under "AB" and "BA" is two questions, and caching one as the
    other would fabricate perfect order-consistency (§9)."""
    project = _project(db, "cachevar", template="side-by-side-preference", labels_per_unit=2)
    _ingest(db, project, _pair_rows(1))
    a = _judge(db, project, name="ja")
    b = _judge(db, project, name="jb")

    run_judge(db, project.id, a.id, provider=MockProvider(model_id="m"))
    run_judge(db, project.id, b.id, provider=MockProvider(model_id="m"))

    entries = db.scalars(select(JudgeCacheEntry)).all()
    # Two configs × one unit × the variant each happened to draw.
    assert len({(e.judge_config_id, e.variant_key) for e in entries}) == len(entries)
    assert all(e.prompt_hash for e in entries)


def test_a_changed_prompt_version_does_not_reuse_the_old_cache(db):
    project = _project(db, "cachever", labels_per_unit=2, max_labels_per_unit=2)
    _ingest(db, project, _image_rows(2))
    v1 = _judge(db, project, name="j", prompt="Be terse.")
    run_judge(db, project.id, v1.id, provider=MockProvider(model_id="m"))

    v2 = new_version(db, v1.id, prompt_template="Be thorough.")
    attach_judge(db, project.id, v2.id)
    result = run_judge(db, project.id, v2.id, provider=MockProvider(model_id="m"))

    assert result.cache_hits == 0, "a new prompt version is a new judge (§7.1)"
    assert result.labels_written == 2


# --- acceptance: budget caps + webhook ---------------------------------------


def test_budget_cap_hard_stops_and_fires_its_webhook(db):
    """M7 acceptance #3. The cap stops the run *and* the operator hears about it."""
    project = _project(db, "budget", labels_per_unit=1)
    _ingest(db, project, _image_rows(10))
    db.add(
        Webhook(
            event="budget.cap_reached",
            target_url="https://example.test/hook",
            secret="s3cret",
            project_id=project.id,
            status="active",
        )
    )
    db.flush()

    config = _judge(db, project, budget={"max_labels": 3})
    recorder = _Recorder()
    result = run_judge(
        db,
        project.id,
        config.id,
        provider=MockProvider(model_id="m"),
        sender=recorder,
        sleep=lambda _: None,
    )

    assert result.labels_written == 3, "the cap is a hard stop, not a suggestion"
    assert result.status == "stopped"
    assert result.stopped_reason == "budget_labels"
    assert result.webhooks_fired == 1

    url, body, headers = recorder.calls[0]
    payload = json.loads(body)
    assert url == "https://example.test/hook"
    assert payload["event"] == "budget.cap_reached"
    assert payload["project_id"] == project.id
    assert payload["metric"]["cap_labels"] == 3
    assert headers["X-MiniLP-Signature"].startswith("sha256=")

    # And a second run refuses to start rather than spending one more call.
    again = run_judge(
        db, project.id, config.id, provider=MockProvider(model_id="m"), sender=recorder
    )
    assert again.labels_written == 0
    assert again.stopped_reason == "budget_labels"


def test_a_dollar_cap_stops_on_spend(db):
    project = _project(db, "dollars", labels_per_unit=1)
    _ingest(db, project, _image_rows(10))
    config = _judge(
        db,
        project,
        params={"price": {"input": 100.0, "output": 100.0}},
        budget={"project_usd": 0.05},
    )
    result = run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))
    assert result.stopped_reason == "budget_project"
    assert result.cost_usd >= 0.05
    assert result.labels_written < 10


def test_spend_is_read_back_from_labels_not_a_counter(db):
    """Caps must survive a process restart, so spend lives in the labels table."""
    project = _project(db, "spend", labels_per_unit=1)
    _ingest(db, project, _image_rows(2))
    config = _judge(db, project, params={"price": {"input": 1000.0, "output": 1000.0}})
    result = run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))

    annotator = db.scalar(select(Annotator).where(Annotator.judge_config_id == config.id))
    spend = judge_spend(db, project.id, annotator.id)
    assert spend.labels == 2
    assert spend.cost_usd == pytest.approx(result.cost_usd, rel=1e-6)


def test_no_webhook_registered_means_no_delivery_and_no_error(db):
    project = _project(db, "nohook", labels_per_unit=1)
    _ingest(db, project, _image_rows(3))
    config = _judge(db, project, budget={"max_labels": 1})
    result = run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))
    assert result.stopped_reason == "budget_labels"
    assert result.webhooks_fired == 0


# --- dry run -----------------------------------------------------------------


def test_dry_run_estimates_cost_without_spending_or_labeling(db):
    project = _project(db, "dry", labels_per_unit=1)
    _ingest(db, project, _image_rows(4))
    config = _judge(db, project, params={"price": {"input": 3.0, "output": 15.0}})

    estimate = dry_run_estimate(db, project.id, config.id, provider=MockProvider(model_id="m"))

    assert estimate.dry_run is True
    assert estimate.slots_attempted == 4
    assert estimate.labels_written == 0
    assert estimate.cost_usd == 0.0
    assert estimate.estimated_cost_usd > 0
    assert db.scalar(select(Label)) is None, "a dry run must write no labels"


def test_dry_run_leaves_every_slot_open_for_the_real_run(db):
    project = _project(db, "dry2", labels_per_unit=1)
    _ingest(db, project, _image_rows(3))
    config = _judge(db, project)

    dry_run_estimate(db, project.id, config.id, provider=MockProvider(model_id="m"))
    live = run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))

    assert live.labels_written == 3, "the dry run stranded slots it should have released"


def test_dry_run_is_recorded_alongside_live_runs(db):
    project = _project(db, "dry3", labels_per_unit=1)
    _ingest(db, project, _image_rows(2))
    config = _judge(db, project)
    dry_run_estimate(db, project.id, config.id, provider=MockProvider(model_id="m"))
    run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))

    runs = db.scalars(select(JudgeRun).order_by(JudgeRun.id)).all()
    assert [r.dry_run for r in runs] == [True, False]
    assert runs[0].estimated_cost_usd is not None
    assert runs[1].estimated_cost_usd is None


# --- limits + failure handling ----------------------------------------------


def test_limit_bounds_a_run(db):
    project = _project(db, "limit", labels_per_unit=1)
    _ingest(db, project, _image_rows(10))
    config = _judge(db, project)
    result = run_judge(db, project.id, config.id, limit=4, provider=MockProvider(model_id="m"))
    assert result.labels_written == 4
    assert result.stopped_reason == "limit"


class _AlwaysBroken(MockProvider):
    def complete(self, request):
        raise ProviderError("upstream is down", status=503, retryable=True)


class _Unparseable(MockProvider):
    def complete(self, request):
        response = super().complete(request)
        return type(response)(
            text="I would rather not say.",
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            model_id=response.model_id,
        )


def test_a_provider_outage_writes_no_labels_and_leaves_slots_open(db):
    project = _project(db, "outage", labels_per_unit=1)
    _ingest(db, project, _image_rows(3))
    config = _judge(db, project, params={"retries": 1})

    result = run_judge(
        db,
        project.id,
        config.id,
        provider=_AlwaysBroken(model_id="m"),
        sleep=lambda _: None,
    )

    assert result.labels_written == 0
    assert result.status == "stopped"
    assert result.stopped_reason == "provider_error"
    assert result.errors and result.errors[0]["stage"] == "provider"
    assert db.scalar(select(Label)) is None
    open_slots = db.scalars(
        select(Slot).join(Unit, Slot.unit_id == Unit.id).where(Unit.project_id == project.id)
    ).all()
    assert all(s.status == "open" for s in open_slots), "a failed call must release its lease"


def test_an_unparseable_reply_releases_the_slot_and_is_reported(db):
    """A judge whose output we could not read must not become a label."""
    project = _project(db, "garbage", labels_per_unit=1)
    _ingest(db, project, _image_rows(2))
    config = _judge(db, project)

    result = run_judge(db, project.id, config.id, provider=_Unparseable(model_id="m"))

    assert result.labels_written == 0
    assert result.slots_attempted == 2
    assert [e["stage"] for e in result.errors] == ["parse", "parse"]
    assert db.scalar(select(Label)) is None
    assert all(s.status == "open" for s in db.scalars(select(Slot)))


# --- cost analytics ----------------------------------------------------------


def test_project_costs_reports_per_judge_spend_and_cache_rate(db):
    project = _project(db, "costs", labels_per_unit=1)
    _ingest(db, project, _image_rows(4))
    config = _judge(db, project, params={"price": {"input": 10.0, "output": 10.0}})
    run_judge(db, project.id, config.id, provider=MockProvider(model_id="m"))

    costs = project_costs(db, project.id)
    row = costs["judges"][0]

    assert row["judge_config_id"] == config.id
    assert row["provider"] == "mock"
    assert row["labels"] == 4
    assert row["cost_per_label"] == pytest.approx(row["cost_usd"] / 4)
    assert row["cache_hit_rate"] == 0.0
    assert costs["totals"]["human_labels"] == 0
    assert costs["totals"]["cost_per_judge_label"] is not None
