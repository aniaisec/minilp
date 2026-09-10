"""Measurement report: a project's exports and analytics, joined with an answer
key the platform never saw, written as ``report.json`` + ``report.md``.

    python -m app.measure.report --api http://localhost:8000 --key $KEY \
        --project 12 --answer-key truth.jsonl --key-field item_id --input sentiment \
        [--planted sim/planted.json] --out study/p12

Needs a reviewer or admin key (exports and analytics are reviewer-gated).
``fetch`` is the only part that talks HTTP; ``build_report`` and
``render_markdown`` are pure, so an archived ``inputs.json`` re-renders offline
with ``--from-inputs``.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.measure.metrics import (
    accuracy,
    annotator_accuracy,
    detection,
    join_units,
    latency,
    parse_answer_key,
    task_flow,
)
from app.measure.simulate import BAD_PERSONAS, GOOD_PERSONAS, Api

AGREEMENT_GROUPS = ("all", "human", "model", "cross")


class ReportError(RuntimeError):
    """The platform refused a request the report needs."""


def _jsonl(raw: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]


def fetch(api: Api, project_id: int) -> dict[str, Any]:
    """Everything the report reads, in one dict — archive it as ``inputs.json``."""

    def get(path: str) -> Any:
        status, body, _ = api.call("GET", path)
        if status != 200:
            raise ReportError(f"GET {path} → {status}: {body}")
        return body

    def export(fmt: str) -> list[dict[str, Any]]:
        path = f"/projects/{project_id}/export?format={fmt}"
        status, raw, _ = api.request("GET", path)
        if status != 200:
            raise ReportError(f"GET {path} → {status}: {raw[:200]!r}")
        return _jsonl(raw)

    base = f"/projects/{project_id}"
    return {
        "project": get(base),
        "labels": export("labels"),
        "raw": export("raw"),
        "events": export("events"),
        "progress": get(f"{base}/progress"),
        "roster": get(f"{base}/annotators"),
        "bias": get(f"{base}/analytics/bias"),
        "agreement": {g: get(f"{base}/analytics/agreement?group={g}") for g in AGREEMENT_GROUPS},
        "costs": get(f"{base}/analytics/costs"),
    }


def build_report(
    inputs: dict[str, Any],
    answer_key: dict[str, Any],
    *,
    input_key: str,
    key_field: str,
    planted: dict[int, str] | None = None,
    bad_personas: frozenset[str] = BAD_PERSONAS,
    good_personas: frozenset[str] = GOOD_PERSONAS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """The study's numbers for one project (docs/MEASUREMENT.md §3)."""
    project = inputs["project"]
    joined = join_units(inputs["labels"], answer_key, input_key=input_key, key_field=key_field)
    quality = accuracy(joined["units"])
    raters = annotator_accuracy(
        inputs["raw"],
        answer_key,
        inputs["roster"].get("annotators", []),
        input_key=input_key,
        key_field=key_field,
        planted=planted,
    )
    progress = inputs["progress"]
    bias = inputs["bias"]
    totals = inputs["costs"].get("totals", {})
    shipped = quality["shipped"]
    correct = round(shipped["estimate"] * shipped["n"]) if shipped else 0
    spend = totals.get("cost_usd") or 0.0
    per_correct = round(spend / correct, 6) if correct and spend else None

    def _bias(group: str) -> dict[str, Any]:
        block = bias.get(group) or {}
        return {
            "prefer_first_rate": block.get("prefer_first_rate"),
            "annotators": {a["annotator_id"]: a["preference"] for a in block.get("annotators", [])},
        }

    return {
        "project": {
            k: project.get(k)
            for k in ("id", "name", "labels_per_unit", "max_labels_per_unit", "gold_ratio")
        },
        "generated_at": generated_at or datetime.now(UTC).isoformat(timespec="seconds"),
        "answer_key": {
            "items": len(answer_key),
            "input_key": input_key,
            "key_field": key_field,
            "units_joined": len(joined["units"]),
            "units_unkeyed": joined["unkeyed"],
        },
        "quality": quality,
        "raters": raters,
        "detection": (
            detection(raters["annotators"], bad_personas, good_personas) if planted else None
        ),
        "flow": {
            "human": task_flow(inputs["events"], annotator_kind="human"),
            "model": task_flow(inputs["events"], annotator_kind="model"),
        },
        "latency": latency(inputs["raw"]),
        "throughput": progress.get("throughput"),
        "funnel": progress.get("funnel"),
        "variants_balanced": (progress.get("variants") or {}).get("balanced"),
        "agreement": {
            group: {
                key: {
                    "kappa": block.get("kappa"),
                    "method": block.get("method"),
                    "mean_entropy": block.get("mean_entropy"),
                    "units": block.get("units_with_multiple_labels"),
                }
                for key, block in (payload.get("keys") or {}).items()
            }
            for group, payload in inputs["agreement"].items()
        },
        "bias": {
            "humans": _bias("humans"),
            "judges": _bias("judges"),
            "order_flip_rate": (bias.get("order_sensitivity") or {}).get("flip_rate"),
        },
        "cost": {
            "judge_labels": totals.get("judge_labels"),
            "human_labels": totals.get("human_labels"),
            "cost_usd": totals.get("cost_usd"),
            "cost_per_judge_label": totals.get("cost_per_judge_label"),
            "cache_hit_rate": totals.get("cache_hit_rate"),
            "cost_per_correct_shipped_label": per_correct,
        },
    }


# --- markdown -------------------------------------------------------------------


def _rate(p: dict[str, Any] | None) -> str:
    # n = 0 is "nothing measured" — the bias endpoint reports it as 0.5 over
    # [0, 1], which printed as a number reads like a finding.
    if not p or not p.get("n"):
        return "—"
    return (
        f"{p['estimate'] * 100:.1f}% [{p['ci_low'] * 100:.1f}–{p['ci_high'] * 100:.1f}] "
        f"(n={p['n']})"
    )


def _num(value: Any, fmt: str = "{}") -> str:
    return "—" if value is None else fmt.format(value)


def _dist(d: dict[str, Any] | None, scale: float = 1.0, unit: str = "") -> str:
    if not d:
        return "—"
    return (
        f"median {d['median'] * scale:.1f}{unit} · p10 {d['p10'] * scale:.1f}{unit} · "
        f"p90 {d['p90'] * scale:.1f}{unit} (n={d['n']})"
    )


def render_markdown(report: dict[str, Any]) -> str:
    p, q, ak = report["project"], report["quality"], report["answer_key"]
    lines = [
        f"# Measurement report — {p['name']} (project {p['id']})",
        "",
        f"Generated {report['generated_at']}. K = {p['labels_per_unit']}"
        f" (max {_num(p['max_labels_per_unit'])}), gold ratio {_num(p['gold_ratio'])}.",
        f"Answer key: {ak['items']} items on `{ak['input_key']}`, joined on "
        f"`payload.{ak['key_field']}` — {ak['units_joined']} units joined, "
        f"{ak['units_unkeyed']} without a key.",
        "",
        "## Label quality (H1, H2)",
        "",
        "| Measure | Accuracy vs answer key [95% CI] |",
        "|---|---|",
    ]
    for kind, rate in q["single_label"].items():
        lines.append(f"| Single label — {kind} | {_rate(rate)} |")
    lines += [
        f"| Majority vote ({q['majority_ties']} ties counted wrong) | {_rate(q['majority'])} |",
        f"| **Shipped label** | **{_rate(q['shipped'])}** |",
    ]
    for method, rate in q["shipped_by_method"].items():
        lines.append(f"| Shipped — {method} | {_rate(rate)} |")
    lines += [
        "",
        f"Coverage (non-gold units with a shipped label): {_rate(q['coverage'])}. "
        f"Lift over majority on {q['paired_units']} paired units: "
        f"{_num(q['lift_over_majority'], '{:+.4f}')}.",
        "",
    ]
    funnel = report.get("funnel") or {}
    if funnel:
        lines.append(
            f"Funnel: {funnel.get('total', 0)} units · finalized {funnel.get('finalized', 0)} · "
            f"escalated {funnel.get('escalated', 0)} · labeled {funnel.get('labeled', 0)} · "
            f"in progress {funnel.get('in_progress', 0)} · pending {funnel.get('pending', 0)}."
        )
        lines.append("")

    raters = report["raters"]
    lines += [
        "## Raters (H3)",
        "",
        f"Spearman(reputation, true accuracy) = "
        f"{_num(raters['reputation_vs_truth_spearman'])}; "
        f"Spearman(gold accuracy, true accuracy) = "
        f"{_num(raters['gold_accuracy_vs_truth_spearman'])} "
        f"(active raters with ≥ {raters['min_labels']} scored labels — a paused rater's "
        f"reputation is recomputed from what survived the void, so it is left out).",
        "",
        "| Annotator | Kind | Persona | Scored | True acc. | Gold acc. | Reputation | Status |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in raters["annotators"]:
        lines.append(
            f"| {r['annotator_id']} {r['name'] or ''} | {_num(r['kind'])} | {_num(r['persona'])} "
            f"| {r['labels_scored']} | {_num(r['true_accuracy'], '{:.3f}')} "
            f"| {_num(r['gold_accuracy'], '{:.3f}')} | {_num(r['reputation'], '{:.3f}')} "
            f"| {_num(r['status'])} |"
        )
    det = report.get("detection")
    if det:
        lines += [
            "",
            f"Planted bad raters: {det['bad_raters']}, paused {det['paused_bad']} — recall "
            f"{_rate(det['recall'])}; good raters paused: {_rate(det['false_pause_rate'])}; "
            f"labels before pause: {_dist(det['labels_before_pause'])}; bad labels still "
            f"valid: {_rate(det['bad_labels_surviving'])}.",
        ]
        if det["grey"]:
            grey = ", ".join(f"{p} {g['paused']}/{g['raters']}" for p, g in det["grey"].items())
            lines.append(f"Grey personas paused (reported, not scored): {grey}.")

    lines += ["", "## Agreement", "", "| Group | Key | κ | Method | Mean entropy | Units |"]
    lines.append("|---|---|---|---|---|---|")
    for group, keys in report["agreement"].items():
        for key, a in keys.items():
            lines.append(
                f"| {group} | {key} | {_num(a['kappa'], '{:.3f}')} | {a['method']} "
                f"| {_num(a['mean_entropy'], '{:.3f}')} | {_num(a['units'])} |"
            )

    bias = report["bias"]
    lines += [
        "",
        "## Order bias (H5)",
        "",
        f"Variants balanced: {_num(report['variants_balanced'])}. "
        f"Order-flip rate: {_num(bias['order_flip_rate'])}.",
        f"- Humans prefer the first position: {_rate(bias['humans']['prefer_first_rate'])}",
        f"- Judges prefer the first position: {_rate(bias['judges']['prefer_first_rate'])}",
    ]

    flow, lat = report["flow"]["human"], report["latency"]
    thr = report.get("throughput") or {}
    lines += [
        "",
        "## Time and task flow (H4) — humans",
        "",
        f"- Time on task (client): {_dist(lat['by_kind'].get('human'), 0.001, ' s')}",
        f"- Lease → submit (server): {_dist(flow['dwell_seconds'].get('submitted'), 1, ' s')}",
        f"- Under {lat['fast_ms']} ms (speed-flag line): {_rate(lat['human_under_fast_ms'])}",
        f"- Episodes {flow['episodes']}: skip {_rate(flow['skip_rate'])}, exit "
        f"{_rate(flow['exit_rate'])}, expiry {_rate(flow['expiry_rate'])}",
        f"- Skips re-served to the same rater next: {_rate(flow['reserved_after_skip'])}",
        f"- Throughput: {_num(thr.get('labels_per_hour'))} labels/hour over the last "
        f"{_num(thr.get('window_hours'))} h",
    ]

    cost = report["cost"]
    lines += [
        "",
        "## Cost (H6)",
        "",
        f"Judge labels {_num(cost['judge_labels'])}, human labels {_num(cost['human_labels'])}; "
        f"spend ${_num(cost['cost_usd'], '{:.4f}')}; $/judge label "
        f"{_num(cost['cost_per_judge_label'], '{:.6f}')}; $/correct shipped label "
        f"{_num(cost['cost_per_correct_shipped_label'], '{:.6f}')}; cache hit rate "
        f"{_num(cost['cache_hit_rate'])}.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--key", help="reviewer/admin API key")
    parser.add_argument("--project", type=int)
    parser.add_argument("--from-inputs", help="re-render from an archived inputs.json instead")
    parser.add_argument("--answer-key", required=True)
    parser.add_argument("--key-field", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--planted", help="planted.json from app.measure.simulate")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    if args.from_inputs:
        inputs = json.loads(Path(args.from_inputs).read_text(encoding="utf-8"))
    elif args.key and args.project:
        inputs = fetch(Api(args.api, args.key), args.project)
    else:
        parser.error("either --from-inputs, or --key and --project")
    answer_key = parse_answer_key(
        Path(args.answer_key).read_text(encoding="utf-8"),
        key_field=args.key_field,
        input_key=args.input,
    )
    planted = None
    if args.planted:
        planted = {int(k): v for k, v in json.loads(Path(args.planted).read_text()).items()}

    report = build_report(
        inputs, answer_key, input_key=args.input, key_field=args.key_field, planted=planted
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not args.from_inputs:
        (out / "inputs.json").write_text(json.dumps(inputs, default=str))
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {out / 'report.md'}")


if __name__ == "__main__":
    main()
