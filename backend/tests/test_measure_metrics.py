"""Measurement metrics (docs/MEASUREMENT.md) — pinned by hand-computed fixtures.

Pure: no database, no network. A study's numbers come from these functions over
archived exports, so the arithmetic is fixed here the same way
``test_analytics_stats`` fixes the dashboard's.
"""

import pytest

from app.measure.metrics import (
    accuracy,
    annotator_accuracy,
    detection,
    join_units,
    latency,
    majority,
    parse_answer_key,
    percentile,
    spearman,
    summarize,
    sus_scores,
    task_flow,
)

# --- primitives ----------------------------------------------------------------


def test_percentile_interpolates_linearly() -> None:
    data = [1.0, 2.0, 3.0, 4.0]
    assert percentile(data, 0.5) == 2.5
    assert percentile(data, 0.1) == pytest.approx(1.3)
    assert percentile(data, 0.9) == pytest.approx(3.7)


def test_summarize_ignores_none_and_reports_nothing_for_no_data() -> None:
    assert summarize([None, None]) is None
    out = summarize([4, None, 1, 3, 2])
    assert out == {"n": 4, "mean": 2.5, "p10": 1.3, "median": 2.5, "p90": 3.7, "max": 4.0}


def test_majority_is_none_on_a_tie_and_handles_list_answers() -> None:
    assert majority([]) is None
    assert majority(["cat", "dog"]) is None
    assert majority(["cat", "dog", "cat"]) == "cat"
    assert majority([["a", "b"], ["a", "b"], ["c"]]) == ["a", "b"]


def test_spearman_hand_computed() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    # ys ranks with a tie: [1, 2.5, 2.5, 4] → rho = 4.5 / sqrt(5 * 4.5)
    assert spearman([1, 2, 3, 4], [1, 5, 5, 9]) == pytest.approx(0.9487, abs=1e-4)
    assert spearman([1, 2], [1, 2]) is None  # too few points
    assert spearman([1, 1, 1], [1, 2, 3]) is None  # no variance


def test_parse_answer_key_requires_both_fields() -> None:
    text = '{"item_id": "a", "category": "cat"}\n\n{"item_id": 7, "category": "dog"}\n'
    assert parse_answer_key(text, key_field="item_id", input_key="category") == {
        "a": "cat",
        "7": "dog",
    }
    with pytest.raises(ValueError, match="line 1"):
        parse_answer_key('{"item_id": "a"}', key_field="item_id", input_key="category")


# --- label quality ----------------------------------------------------------------


def _row(unit_id, item, votes, final=None, method=None, gold=False):
    return {
        "unit_id": unit_id,
        "payload": {"item_id": item},
        "is_gold": gold,
        "final_label": {"category": final} if final else {},
        "final_method": method,
        "labels": [
            {"annotator_id": aid, "annotator_kind": kind, "value": {"category": v}}
            for aid, kind, v in votes
        ],
    }


KEY = {"u1": "cat", "u2": "dog", "u3": "bird", "g1": "cat"}
LABEL_ROWS = [
    _row(
        1,
        "u1",
        [(1, "human", "cat"), (2, "human", "cat"), (9, "model", "dog")],
        "cat",
        "auto_consensus",
    ),
    _row(2, "u2", [(1, "human", "cat"), (9, "model", "dog")], "dog", "human_override"),
    _row(3, "u3", [(2, "human", "cat"), (9, "model", "cat")], "cat", "auto_consensus"),
    _row(4, "g1", [(1, "human", "dog")], gold=True),
    _row(5, "not-in-key", [(1, "human", "cat")]),
    {"unit_id": 6, "payload": {}, "labels": []},
]


def test_join_units_counts_rather_than_guesses_unkeyed_units() -> None:
    joined = join_units(LABEL_ROWS, KEY, input_key="category", key_field="item_id")
    assert joined["unkeyed"] == 2
    assert [u["unit_id"] for u in joined["units"]] == [1, 2, 3, 4]
    assert joined["units"][0]["votes"][2] == {"annotator_id": 9, "kind": "model", "value": "dog"}


def test_accuracy_hand_computed() -> None:
    units = join_units(LABEL_ROWS, KEY, input_key="category", key_field="item_id")["units"]
    out = accuracy(units)
    assert out["units_scored"] == 3  # the gold is excluded
    # human votes: u1 cat✓ cat✓, u2 cat✗, u3 cat✗ → 2/4; model: u1✗ u2✓ u3✗ → 1/3
    assert out["single_label"]["human"]["estimate"] == 0.5
    assert out["single_label"]["human"]["n"] == 4
    assert out["single_label"]["model"]["estimate"] == pytest.approx(0.3333, abs=1e-4)
    # majority: u1 cat✓, u2 tie (wrong), u3 cat✗
    assert out["majority"]["estimate"] == pytest.approx(0.3333, abs=1e-4)
    assert out["majority_ties"] == 1
    # shipped: u1✓ u2✓ (the override fixed it) u3✗
    assert out["shipped"]["estimate"] == pytest.approx(0.6667, abs=1e-4)
    assert out["coverage"]["estimate"] == 1.0
    assert out["shipped_by_method"]["auto_consensus"]["estimate"] == 0.5
    assert out["shipped_by_method"]["human_override"]["estimate"] == 1.0
    assert out["lift_over_majority"] == pytest.approx(0.3333, abs=1e-4)


def test_accuracy_on_nothing_reports_none_not_zero() -> None:
    out = accuracy([])
    assert out["shipped"] is None and out["majority"] is None
    assert out["lift_over_majority"] is None


# --- raters -----------------------------------------------------------------------


def _raw(aid, item, answer, *, valid=True, gold=False, kind="human", latency_ms=None):
    return {
        "annotator_id": aid,
        "annotator_kind": kind,
        "payload": {"item_id": item},
        "value": {"category": answer},
        "is_valid": valid,
        "is_gold": gold,
        "latency_ms": latency_ms,
    }


def test_annotator_accuracy_counts_voided_work_and_skips_golds() -> None:
    raw = [
        _raw(1, "u1", "cat"),
        _raw(1, "u2", "dog"),
        _raw(1, "g1", "dog", gold=True),  # golds are excluded from true accuracy
        _raw(2, "u1", "dog", valid=False),  # voided, still scored
        _raw(2, "u2", "cat", valid=False),
    ]
    roster = [
        {
            "annotator_id": 1,
            "display_name": "a",
            "kind": "human",
            "reputation": 0.9,
            "gold_accuracy": 1.0,
            "status": "active",
            "labels_valid": 3,
            "labels_voided": 0,
        },
        {
            "annotator_id": 2,
            "display_name": "b",
            "kind": "human",
            "reputation": 0.2,
            "gold_accuracy": 0.0,
            "status": "paused",
            "labels_valid": 0,
            "labels_voided": 2,
        },
    ]
    out = annotator_accuracy(
        raw,
        KEY,
        roster,
        input_key="category",
        key_field="item_id",
        planted={2: "spammer", 1: "expert"},
        min_labels=1,
    )
    a, b = out["annotators"]
    assert (a["true_accuracy"], a["labels_scored"], a["persona"]) == (1.0, 2, "expert")
    assert (b["true_accuracy"], b["labels_scored_valid"], b["labels_total"]) == (0.0, 0, 2)
    assert out["reputation_vs_truth_spearman"] is None  # two raters are not a correlation


def test_detection_scores_pauses_against_planted_personas() -> None:
    rows = [
        {
            "persona": "spammer",
            "status": "paused",
            "labels_total": 40,
            "labels_scored": 30,
            "labels_scored_valid": 10,
        },
        {
            "persona": "spammer",
            "status": "active",
            "labels_total": 90,
            "labels_scored": 80,
            "labels_scored_valid": 80,
        },
        {
            "persona": "typical",
            "status": "paused",
            "labels_total": 50,
            "labels_scored": 45,
            "labels_scored_valid": 25,
        },
        {
            "persona": "typical",
            "status": "active",
            "labels_total": 50,
            "labels_scored": 45,
            "labels_scored_valid": 45,
        },
        {
            "persona": "biased",  # grey: reported, not scored as a false pause
            "status": "paused",
            "labels_total": 30,
            "labels_scored": 25,
            "labels_scored_valid": 5,
        },
        {
            "persona": None,
            "status": "paused",
            "labels_total": 5,
            "labels_scored": 5,
            "labels_scored_valid": 5,
        },
    ]
    out = detection(rows, {"spammer"}, {"typical", "expert"})
    assert out["bad_raters"] == 2 and out["paused_bad"] == 1 and out["paused_good"] == 1
    assert out["grey"] == {"biased": {"raters": 1, "paused": 1}}
    assert out["recall"]["estimate"] == 0.5
    assert out["false_pause_rate"]["estimate"] == 0.5
    assert out["labels_before_pause"]["median"] == 40.0
    assert out["bad_labels_surviving"]["estimate"] == pytest.approx(90 / 110, abs=1e-4)
    assert detection([{"persona": None, "status": "active"}], {"spammer"}, {"typical"}) is None


def test_paused_raters_are_left_out_of_the_reputation_correlation() -> None:
    """A paused rater's roster reputation drifts back toward the prior once their
    golds are voided — here the paused rater's 0.95 would wreck a clean ranking."""
    key = {"a": "cat", "b": "dog"}
    raw = [
        _raw(aid, item, answer)
        for aid, answers in {
            1: ("cat", "dog"),
            2: ("cat", "cat"),
            3: ("dog", "cat"),
            4: ("dog", "cat"),
        }.items()
        for item, answer in zip(("a", "b"), answers, strict=True)
    ]
    roster = [
        {"annotator_id": aid, "reputation": rep, "gold_accuracy": None, "status": status}
        for aid, rep, status in (
            (1, 0.9, "active"),
            (2, 0.6, "active"),
            (3, 0.3, "active"),
            (4, 0.95, "paused"),
        )
    ]
    out = annotator_accuracy(
        raw, key, roster, input_key="category", key_field="item_id", min_labels=1
    )
    assert [r["true_accuracy"] for r in out["annotators"]] == [1.0, 0.5, 0.0, 0.0]
    assert out["reputation_vs_truth_spearman"] == 1.0


# --- flow, time, survey ---------------------------------------------------------------


def _event(eid, slot, kind, second, aid=1, akind="human"):
    return {
        "event_id": eid,
        "slot_id": slot,
        "annotator_id": aid,
        "annotator_kind": akind,
        "kind": kind,
        "at": f"2026-09-10T10:00:{second:02d}+00:00",
    }


def test_task_flow_reconstructs_episodes() -> None:
    events = [
        _event(1, 10, "leased", 0),
        _event(2, 10, "submitted", 5),
        _event(3, 11, "leased", 10),
        _event(4, 11, "skipped", 12),
        _event(5, 11, "leased", 13),  # the slot just skipped, straight back
        _event(6, 11, "resumed", 14),  # a reload continues the episode
        _event(7, 11, "submitted", 20),
        _event(8, 12, "leased", 30),
        _event(9, 12, "expired", 59),
        _event(10, 13, "leased", 1, aid=9, akind="model"),  # other kind: ignored
        _event(11, 13, "released", 2, aid=9, akind="model"),
    ]
    out = task_flow(events)
    assert out["episodes"] == 4
    assert out["outcomes"] == {"expired": 1, "skipped": 1, "submitted": 2}
    assert out["resumes"] == 1 and out["still_open"] == 0
    assert out["skip_rate"]["estimate"] == 0.25
    assert out["reserved_after_skip"]["estimate"] == 1.0
    assert out["dwell_seconds"]["submitted"]["median"] == 6.0  # 5s and 7s
    assert out["dwell_seconds"]["expired"]["max"] == 29.0
    assert task_flow(events, annotator_kind="model")["outcomes"] == {"released": 1}


def test_latency_splits_kinds_and_counts_fast_human_labels() -> None:
    raw = [
        _raw(1, "u1", "cat", latency_ms=800),
        _raw(1, "u2", "cat", latency_ms=4000),
        _raw(1, "u3", "cat", latency_ms=500, valid=False),  # voided: not counted
        _raw(9, "u1", "cat", latency_ms=300, kind="model"),
    ]
    out = latency(raw)
    assert out["by_kind"]["human"]["n"] == 2
    assert out["by_kind"]["model"]["median"] == 300.0
    assert out["human_under_fast_ms"]["estimate"] == 0.5


def test_sus_scores_hand_computed() -> None:
    def answers(aid, per_item):
        return [
            {
                "annotator_id": aid,
                "is_valid": True,
                "payload": {"item": i},
                "value": {"agreement": per_item(i)},
            }
            for i in range(1, 11)
        ]

    best = answers(1, lambda i: 5 if i % 2 else 1)  # (4×5 + 4×5) × 2.5
    flat = answers(2, lambda i: 5)  # odd 4×5, even 0 → 50
    partial = answers(3, lambda i: 3)[:9]  # nine statements: left out
    out = sus_scores(best + flat + partial)
    assert out["participants"] == {1: 100.0, 2: 50.0}
    assert out["incomplete"] == 1
    assert out["summary"]["mean"] == 75.0
