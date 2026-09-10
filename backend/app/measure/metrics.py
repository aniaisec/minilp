"""Pure metrics for a labeling study (docs/MEASUREMENT.md).

Nothing here touches the database or the network. Every function takes rows the
platform already exports (``labels``, ``raw``, ``events``) plus an **answer key
the platform never saw**, and returns plain dicts — the same discipline
``services.analytics.stats`` follows, so the arithmetic is pinned by
hand-computed fixtures and a study can be recomputed from its archived exports.

Why an answer key held outside the platform: golds *are* ground truth, but they
feed reputation, pausing and merge weights. Scoring the pipeline against its own
inputs would be circular. The answer key covers the non-gold units and is joined
on a payload field (``key_field``) after the fact.

Answers are compared by exact canonical token (``stats.token``), which is right
for the categorical keys a study scores; ``within``/``jaccard`` keys would need
their match rule applied first.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from app.services.analytics.stats import token, wilson_interval

TERMINAL_EVENTS = ("submitted", "skipped", "exited", "expired", "released")


# --- primitives ---------------------------------------------------------------


def proportion(successes: int, n: int) -> dict[str, Any] | None:
    """A rate with its Wilson 95% CI, or None when there is nothing to measure."""
    return wilson_interval(successes, n).as_dict() if n else None


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted, non-empty sequence."""
    if not sorted_values:
        raise ValueError("percentile of an empty sequence")
    pos = (len(sorted_values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def summarize(values: Iterable[float | None]) -> dict[str, Any] | None:
    """n / mean / p10 / median / p90 / max, or None with no data."""
    data = sorted(float(v) for v in values if v is not None)
    if not data:
        return None
    return {
        "n": len(data),
        "mean": round(sum(data) / len(data), 2),
        "p10": round(percentile(data, 0.10), 2),
        "median": round(percentile(data, 0.50), 2),
        "p90": round(percentile(data, 0.90), 2),
        "max": round(data[-1], 2),
    }


def same(answer: Any, truth: Any) -> bool:
    return answer is not None and token(answer) == token(truth)


def majority(values: Iterable[Any]) -> Any | None:
    """The plurality answer, or None when the top is tied or there are no votes."""
    counts: Counter[str] = Counter()
    first_seen: dict[str, Any] = {}
    for value in values:
        key = token(value)
        counts[key] += 1
        first_seen.setdefault(key, value)
    if not counts:
        return None
    ranked = counts.most_common(2)
    if len(ranked) == 2 and ranked[0][1] == ranked[1][1]:
        return None
    return first_seen[ranked[0][0]]


def _ranks(xs: Sequence[float]) -> list[float]:
    """1-based ranks, ties sharing their average rank."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman's rank correlation; None below 3 points or with no variance."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return round(cov / math.sqrt(vx * vy), 4)


# --- answer key -----------------------------------------------------------------


def parse_answer_key(text: str, *, key_field: str, input_key: str) -> dict[str, Any]:
    """JSONL, one ``{key_field: id, input_key: answer}`` object per line."""
    key: dict[str, Any] = {}
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if key_field not in row or input_key not in row:
            raise ValueError(f"answer key line {n}: needs '{key_field}' and '{input_key}'")
        key[str(row[key_field])] = row[input_key]
    return key


def join_units(
    label_rows: Iterable[Mapping[str, Any]],
    answer_key: Mapping[str, Any],
    *,
    input_key: str,
    key_field: str,
) -> dict[str, Any]:
    """Attach ground truth to each ``labels``-export row.

    Units whose payload lacks ``key_field``, or whose id the answer key does not
    cover, are counted rather than guessed at.
    """
    units = []
    unkeyed = 0
    for row in label_rows:
        item = (row.get("payload") or {}).get(key_field)
        if item is None or str(item) not in answer_key:
            unkeyed += 1
            continue
        units.append(
            {
                "unit_id": row["unit_id"],
                "item": str(item),
                "truth": answer_key[str(item)],
                "is_gold": bool(row.get("is_gold")),
                "escalated": bool(row.get("escalated")),
                "final": (row.get("final_label") or {}).get(input_key),
                "final_method": row.get("final_method"),
                "votes": [
                    {
                        "annotator_id": label.get("annotator_id"),
                        "kind": label.get("annotator_kind"),
                        "value": (label.get("value") or {}).get(input_key),
                    }
                    for label in row.get("labels") or []
                ],
            }
        )
    return {"units": units, "unkeyed": unkeyed}


# --- label quality ----------------------------------------------------------------


def accuracy(units: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Is the answer MiniLP ships better than the raters it was built from?

    Scored on non-gold units only (golds are the platform's own inputs).

    single_label       every valid vote vs truth, by annotator kind
    majority           unweighted plurality of a unit's valid votes (a tie is wrong)
    shipped            the export's final label: the decided row, else agreed consensus
    shipped_by_method  the same, split by how it was decided
    lift_over_majority shipped − majority on units that have both — what reputation
                       weighting, overlap growth and review add over a plain vote
    """
    scored = [u for u in units if not u["is_gold"]]
    single: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_method: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    maj_ok = maj_n = maj_ties = 0
    ship_ok = ship_n = 0
    paired_ship = paired_maj = paired_n = 0
    for unit in scored:
        truth = unit["truth"]
        votes = [v for v in unit["votes"] if v["value"] is not None]
        for vote in votes:
            tally = single[vote["kind"] or "unknown"]
            tally[0] += same(vote["value"], truth)
            tally[1] += 1
        winner = majority(v["value"] for v in votes)
        if votes:
            maj_n += 1
            maj_ties += winner is None
            maj_ok += same(winner, truth)
        if unit["final"] is not None:
            ok = same(unit["final"], truth)
            ship_ok += ok
            ship_n += 1
            # No decided row yet: the export falls back to agreed consensus
            # (services/export/jsonl.py) — shipped, but not by routing.
            tally = by_method[unit["final_method"] or "undecided_consensus"]
            tally[0] += ok
            tally[1] += 1
            if votes:
                paired_n += 1
                paired_ship += ok
                paired_maj += same(winner, truth)
    return {
        "units_scored": len(scored),
        "single_label": {k: proportion(*v) for k, v in sorted(single.items())},
        "majority": proportion(maj_ok, maj_n),
        "majority_ties": maj_ties,
        "shipped": proportion(ship_ok, ship_n),
        "coverage": proportion(ship_n, len(scored)),
        "shipped_by_method": {k: proportion(*v) for k, v in sorted(by_method.items())},
        "paired_units": paired_n,
        "lift_over_majority": round((paired_ship - paired_maj) / paired_n, 4) if paired_n else None,
    }


# --- raters ----------------------------------------------------------------------


def annotator_accuracy(
    raw_rows: Iterable[Mapping[str, Any]],
    answer_key: Mapping[str, Any],
    roster_rows: Iterable[Mapping[str, Any]],
    *,
    input_key: str,
    key_field: str,
    planted: Mapping[int, str] | None = None,
    min_labels: int = 5,
) -> dict[str, Any]:
    """Each rater's accuracy against the answer key, beside what the platform
    thinks of them — does reputation measure what it claims to?

    Reads the ``raw`` export, which keeps voided labels: a paused spammer's
    accuracy has to include the work the pipeline threw away, or every paused
    rater would look better than they were.
    """
    tallies: dict[int, dict[str, int]] = defaultdict(lambda: {"ok": 0, "n": 0, "valid": 0})
    for row in raw_rows:
        if row.get("is_gold"):
            continue
        item = (row.get("payload") or {}).get(key_field)
        answer = (row.get("value") or {}).get(input_key)
        if item is None or str(item) not in answer_key or answer is None:
            continue
        tally = tallies[row["annotator_id"]]
        tally["n"] += 1
        tally["ok"] += same(answer, answer_key[str(item)])
        tally["valid"] += bool(row.get("is_valid"))

    roster = {r["annotator_id"]: r for r in roster_rows}
    planted = planted or {}
    rows = []
    for aid in sorted(set(tallies) | set(roster)):
        tally = tallies.get(aid, {"ok": 0, "n": 0, "valid": 0})
        r = roster.get(aid, {})
        rows.append(
            {
                "annotator_id": aid,
                "name": r.get("display_name"),
                "kind": r.get("kind"),
                "persona": planted.get(aid),
                "labels_scored": tally["n"],
                "labels_scored_valid": tally["valid"],
                "true_accuracy": round(tally["ok"] / tally["n"], 4) if tally["n"] else None,
                "reputation": r.get("reputation"),
                "gold_accuracy": r.get("gold_accuracy"),
                "status": r.get("status"),
                "labels_total": r.get("labels_valid", 0) + r.get("labels_voided", 0),
            }
        )

    # Paused raters are left out of the correlations: pausing voids their recent
    # labels, voided golds drop out of gold accuracy (reputation.gold_accuracy),
    # and the roster's reputation for them drifts back toward the prior. Their
    # story is told by ``detection`` instead.
    def _corr(field: str) -> float | None:
        pts = [
            (r[field], r["true_accuracy"])
            for r in rows
            if r["labels_scored"] >= min_labels and r[field] is not None and r["status"] != "paused"
        ]
        return spearman([p[0] for p in pts], [p[1] for p in pts])

    return {
        "annotators": rows,
        "min_labels": min_labels,
        "reputation_vs_truth_spearman": _corr("reputation"),
        "gold_accuracy_vs_truth_spearman": _corr("gold_accuracy"),
    }


def detection(
    annotator_rows: Iterable[Mapping[str, Any]],
    bad_personas: Iterable[str],
    good_personas: Iterable[str],
) -> dict[str, Any] | None:
    """Did the quality pipeline stop the raters planted to be stopped — and
    only them?

    Only meaningful for a simulated run (``persona`` set). A pause of a *good*
    persona is a false pause; personas in neither set (noisy, biased) are grey:
    whether they should be stopped is policy, so their pauses are listed, not
    scored. ``bad_labels_surviving`` is the share of a bad rater's scored labels
    still valid — the spam that made it into the dataset despite the pause.
    """
    bad, good = set(bad_personas), set(good_personas)
    planted = [r for r in annotator_rows if r.get("persona")]
    if not planted:
        return None
    bad_rows = [r for r in planted if r["persona"] in bad]
    good_rows = [r for r in planted if r["persona"] in good]
    caught = [r for r in bad_rows if r["status"] == "paused"]
    false_pauses = [r for r in good_rows if r["status"] == "paused"]
    grey: dict[str, dict[str, int]] = defaultdict(lambda: {"raters": 0, "paused": 0})
    for r in planted:
        if r["persona"] not in bad | good:
            grey[r["persona"]]["raters"] += 1
            grey[r["persona"]]["paused"] += r["status"] == "paused"
    return {
        "bad_raters": len(bad_rows),
        "paused_bad": len(caught),
        "paused_good": len(false_pauses),
        "recall": proportion(len(caught), len(bad_rows)),
        "false_pause_rate": proportion(len(false_pauses), len(good_rows)),
        "grey": dict(sorted(grey.items())),
        "labels_before_pause": summarize(r["labels_total"] for r in caught),
        "bad_labels_surviving": proportion(
            sum(r["labels_scored_valid"] for r in bad_rows),
            sum(r["labels_scored"] for r in bad_rows),
        ),
    }


# --- task flow and time ------------------------------------------------------------


def task_flow(
    event_rows: Iterable[Mapping[str, Any]], *, annotator_kind: str | None = "human"
) -> dict[str, Any]:
    """Reconstruct lease episodes from the ``events`` export.

    An episode opens at ``leased`` and closes at the next terminal event for the
    same slot and annotator; ``resumed`` continues it (a reload is not a new
    task). ``reserved_after_skip`` counts skips whose very next lease by the
    same annotator was the slot they had just skipped.
    """
    open_at: dict[tuple[int, int | None], datetime] = {}
    last_skipped: dict[int | None, int] = {}
    outcomes: Counter[str] = Counter()
    dwell: dict[str, list[float]] = defaultdict(list)
    resumes = reserved = 0
    ordered = sorted(event_rows, key=lambda e: (e["at"], e["event_id"]))
    for event in ordered:
        if annotator_kind and event.get("annotator_kind") != annotator_kind:
            continue
        who = event.get("annotator_id")
        key = (event["slot_id"], who)
        at = datetime.fromisoformat(event["at"])
        kind = event["kind"]
        if kind == "leased":
            if last_skipped.pop(who, None) == event["slot_id"]:
                reserved += 1
            open_at[key] = at
        elif kind == "resumed":
            resumes += 1
            open_at.setdefault(key, at)
        elif kind in TERMINAL_EVENTS:
            outcomes[kind] += 1
            start = open_at.pop(key, None)
            if start is not None:
                dwell[kind].append((at - start).total_seconds())
            if kind == "skipped":
                last_skipped[who] = event["slot_id"]
    episodes = sum(outcomes.values())
    return {
        "episodes": episodes,
        "outcomes": dict(sorted(outcomes.items())),
        "still_open": len(open_at),
        "resumes": resumes,
        "skip_rate": proportion(outcomes["skipped"], episodes),
        "exit_rate": proportion(outcomes["exited"], episodes),
        "expiry_rate": proportion(outcomes["expired"], episodes),
        "reserved_after_skip": proportion(reserved, outcomes["skipped"]),
        "dwell_seconds": {k: summarize(v) for k, v in sorted(dwell.items())},
    }


def sus_scores(
    raw_rows: Iterable[Mapping[str, Any]], *, item_field: str = "item", input_key: str = "agreement"
) -> dict[str, Any]:
    """System Usability Scale, from a survey project collected through MiniLP.

    One unit per SUS statement (``payload[item_field]`` = 1..10), one likert
    answer (1–5) per participant per statement — the annotator-unit exclusion is
    what guarantees each participant answers each statement exactly once. Odd
    statements are positive (score − 1), even ones negative (5 − score); the sum
    × 2.5 is the 0–100 SUS score. Participants missing a statement are left out.
    """
    answers: dict[int, dict[int, int]] = defaultdict(dict)
    for row in raw_rows:
        if not row.get("is_valid"):
            continue
        item = (row.get("payload") or {}).get(item_field)
        value = (row.get("value") or {}).get(input_key)
        if isinstance(item, int) and 1 <= item <= 10 and isinstance(value, int):
            answers[row["annotator_id"]][item] = value
    scores = {
        aid: 2.5 * sum((v - 1) if item % 2 else (5 - v) for item, v in items.items())
        for aid, items in sorted(answers.items())
        if len(items) == 10
    }
    return {
        "participants": scores,
        "incomplete": sum(1 for items in answers.values() if len(items) < 10),
        "summary": summarize(scores.values()),
    }


def latency(raw_rows: Iterable[Mapping[str, Any]], *, fast_ms: int = 1200) -> dict[str, Any]:
    """Client-reported time on task per annotator kind (valid labels only), and
    the share of human labels under ``fast_ms`` (the §6.2 speed-flag line)."""
    by_kind: dict[str, list[float]] = defaultdict(list)
    for row in raw_rows:
        if row.get("is_valid") and row.get("latency_ms") is not None:
            by_kind[row.get("annotator_kind") or "unknown"].append(row["latency_ms"])
    human = by_kind.get("human", [])
    return {
        "by_kind": {k: summarize(v) for k, v in sorted(by_kind.items())},
        "human_under_fast_ms": proportion(sum(1 for v in human if v < fast_ms), len(human)),
        "fast_ms": fast_ms,
    }
