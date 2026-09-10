"""Measurement report assembly (docs/MEASUREMENT.md) — pure, from archived inputs.

``fetch`` is the only HTTP in the report; everything it returns is fed here as a
fixture, which is also what ``--from-inputs`` does with an archived study.
"""

from app.measure.report import build_report, render_markdown


def _label(aid, kind, answer):
    return {"annotator_id": aid, "annotator_kind": kind, "value": {"sentiment": answer}}


def _raw(aid, kind, item, answer, latency_ms):
    return {
        "annotator_id": aid,
        "annotator_kind": kind,
        "payload": {"item_id": item},
        "value": {"sentiment": answer},
        "is_valid": True,
        "is_gold": False,
        "latency_ms": latency_ms,
    }


INPUTS = {
    "project": {
        "id": 3,
        "name": "Study — sentiment",
        "labels_per_unit": 2,
        "max_labels_per_unit": 3,
        "gold_ratio": 0.1,
    },
    "labels": [
        {
            "unit_id": 1,
            "payload": {"item_id": "s1"},
            "is_gold": False,
            "final_label": {"sentiment": "positive"},
            "final_method": "auto_consensus",
            "labels": [_label(1, "human", "positive"), _label(9, "model", "positive")],
        },
        {
            "unit_id": 2,
            "payload": {"item_id": "s2"},
            "is_gold": False,
            "final_label": {},
            "final_method": None,
            "labels": [_label(1, "human", "neutral"), _label(9, "model", "negative")],
        },
    ],
    "raw": [
        _raw(1, "human", "s1", "positive", 4200),
        _raw(1, "human", "s2", "neutral", 6100),
        _raw(9, "model", "s1", "positive", 900),
        _raw(9, "model", "s2", "negative", 950),
    ],
    "events": [
        {
            "event_id": 1,
            "slot_id": 1,
            "annotator_id": 1,
            "annotator_kind": "human",
            "kind": "leased",
            "at": "2026-09-10T10:00:00+00:00",
        },
        {
            "event_id": 2,
            "slot_id": 1,
            "annotator_id": 1,
            "annotator_kind": "human",
            "kind": "submitted",
            "at": "2026-09-10T10:00:04+00:00",
        },
    ],
    "progress": {
        "funnel": {"total": 2, "finalized": 1, "escalated": 1},
        "throughput": {"labels_per_hour": 4.0, "window_hours": 24.0},
        "variants": {"balanced": True},
    },
    "roster": {
        "annotators": [
            {
                "annotator_id": 1,
                "display_name": "pilot-01",
                "kind": "human",
                "reputation": 0.9,
                "gold_accuracy": None,
                "status": "active",
                "labels_valid": 2,
                "labels_voided": 0,
            },
            {
                "annotator_id": 9,
                "display_name": "judge",
                "kind": "model",
                "reputation": 0.8,
                "gold_accuracy": None,
                "status": "active",
                "labels_valid": 2,
                "labels_voided": 0,
            },
        ]
    },
    "bias": {
        "humans": {
            "prefer_first_rate": {"estimate": 0.5, "ci_low": 0.0, "ci_high": 1.0, "n": 0},
            "annotators": [],
        },
        "judges": {},
        "order_sensitivity": {"flip_rate": None},
    },
    "agreement": {
        "all": {
            "keys": {
                "sentiment": {
                    "kappa": 0.0,
                    "method": "cohen",
                    "mean_entropy": 0.5,
                    "units_with_multiple_labels": 2,
                }
            }
        },
        "cross": {"keys": {}},
    },
    "costs": {
        "totals": {
            "judge_labels": 2,
            "human_labels": 2,
            "cost_usd": 0.01,
            "cost_per_judge_label": 0.005,
            "cache_hit_rate": 0.0,
        }
    },
}
KEY = {"s1": "positive", "s2": "negative"}


def test_build_report_joins_everything_on_the_answer_key() -> None:
    report = build_report(INPUTS, KEY, input_key="sentiment", key_field="item_id", generated_at="t")
    q = report["quality"]
    assert q["single_label"]["human"]["estimate"] == 0.5
    assert q["single_label"]["model"]["estimate"] == 1.0
    assert q["shipped"]["estimate"] == 1.0 and q["coverage"]["estimate"] == 0.5
    assert report["cost"]["cost_per_correct_shipped_label"] == 0.01  # $0.01 / 1 correct
    assert report["flow"]["human"]["dwell_seconds"]["submitted"]["median"] == 4.0
    assert report["latency"]["by_kind"]["human"]["median"] == 5150.0
    assert report["detection"] is None  # no planted personas: not a simulated run
    assert report["agreement"]["all"]["sentiment"]["kappa"] == 0.0


def test_markdown_renders_missing_numbers_as_dashes() -> None:
    report = build_report(
        INPUTS,
        KEY,
        input_key="sentiment",
        key_field="item_id",
        planted={1: "typical"},
        generated_at="t",
    )
    md = render_markdown(report)
    assert md.startswith("# Measurement report — Study — sentiment (project 3)")
    for heading in (
        "## Label quality",
        "## Raters",
        "## Agreement",
        "## Order bias",
        "## Time and task flow",
        "## Cost",
    ):
        assert heading in md
    assert "| **Shipped label** | **100.0%" in md
    assert "Judges prefer the first position: —" in md
    assert "Planted bad raters: 0" in md  # typical only: nothing to catch, and it says so
