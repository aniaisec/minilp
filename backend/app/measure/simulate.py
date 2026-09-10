"""Simulated raters: drive a project through the real HTTP API with raters of
known quality, so the platform can be measured against a truth it cannot see.

Humans tell you how the platform performs with humans. They cannot tell you
whether the quality pipeline catches a spammer, because you do not know who the
spammers are. A simulated run plants them: every rater has a persona (accuracy,
speed, skip/exit habits, position bias) and the report scores the pipeline's
pauses, weights and merges against the personas it was never told.

It also doubles as the load test — every call is timed client-side, so a run
with many raters at ``--time-scale 0`` reports next/submit/skip latency under
concurrency.

    python -m app.measure.simulate --api http://localhost:8000 --project 12 \
        --raters raters.json --answer-key truth.jsonl --key-field item_id \
        --input sentiment --mix typical:5,expert:1,noisy:1,spammer:1 --out sim/

``--raters`` is the file ``app.measure.provision --out`` writes. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.measure.metrics import parse_answer_key, same, summarize
from app.services.quality.canonical import canonicalize_positional


class SimulationError(ValueError):
    """The run cannot be simulated as configured."""


@dataclass(frozen=True)
class Persona:
    name: str
    accuracy: float | None  # P(answer = truth); None answers uniformly at random
    latency_ms: tuple[int, int]  # think time, uniform in [lo, hi]
    skip_rate: float = 0.0
    exit_rate: float = 0.0
    first_option_rate: float = 0.0  # P(pick the first/left option regardless of truth)


PERSONAS: dict[str, Persona] = {
    "expert": Persona("expert", 0.95, (2500, 7000), skip_rate=0.02),
    "typical": Persona("typical", 0.85, (3000, 9000), skip_rate=0.03, exit_rate=0.01),
    "noisy": Persona("noisy", 0.65, (2000, 6000), skip_rate=0.05),
    "spammer": Persona("spammer", None, (300, 900)),
    "biased": Persona("biased", 0.85, (2500, 7000), first_option_rate=0.6),
}

# The personas a working quality pipeline should pause. ``noisy`` is deliberately
# not here: at 0.65 it sits near the default gold threshold, and whether it
# should be stopped is a policy question the report shows rather than scores.
BAD_PERSONAS = frozenset({"spammer"})
# The personas it must never pause — a pause here is a false positive. The rest
# (noisy, biased) are grey: their pauses are reported, not scored.
GOOD_PERSONAS = frozenset({"expert", "typical"})
MAX_ERRORS_KEPT = 5


def parse_mix(mix: str) -> list[str]:
    """``"typical:5,spammer:1"`` → ``["typical", ×5, "spammer"]``."""
    out: list[str] = []
    for part in mix.split(","):
        name, _, count = part.strip().partition(":")
        if name not in PERSONAS:
            raise SimulationError(f"unknown persona '{name}' (known: {sorted(PERSONAS)})")
        out.extend([name] * int(count or 1))
    return out


def answer_options(field: dict[str, Any]) -> list[Any]:
    """The discrete answers an input accepts, in display order."""
    if field.get("options"):
        return list(field["options"])
    if field.get("type") in ("likert", "rating"):
        scale = field.get("scale") or {}
        lo, hi = int(scale.get("min", 1)), int(scale.get("max", 5))
        return list(range(lo, hi + 1))
    if field.get("type") == "boolean":
        return [True, False]
    return []


def choose_answer(
    persona: Persona,
    field: dict[str, Any],
    truth: Any,
    variant: str | None,
    rng: random.Random,
) -> Any:
    """A raw answer as this persona would give it.

    For a positional input (``choice_buttons`` under a variant) the options are
    sides and the truth is an item, so "correct" means clicking whichever side
    the true item is shown on — exactly the mapping the server canonicalizes back.
    """
    options = answer_options(field)
    if not options:
        raise SimulationError(f"input '{field.get('id')}' has no discrete options to simulate")
    positional = field.get("type") == "choice_buttons" and bool(variant)

    def canonical(option: Any) -> Any:
        return canonicalize_positional(option, variant) if positional else option

    if persona.first_option_rate and rng.random() < persona.first_option_rate:
        return options[0]
    if truth is None or persona.accuracy is None:
        return rng.choice(options)
    right = [o for o in options if same(canonical(o), truth)]
    wrong = [o for o in options if not same(canonical(o), truth)]
    if right and (not wrong or rng.random() < persona.accuracy):
        return rng.choice(right)
    return rng.choice(wrong)


class Api:
    """A minimal JSON client that times every call."""

    def __init__(self, base: str, key: str) -> None:
        self.base = base.rstrip("/")
        self.key = key

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, bytes, float]:
        """Status, body bytes and elapsed ms — for callers that are not JSON (JSONL)."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — operator-given URL
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        return status, raw, (time.perf_counter() - started) * 1000

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, Any, float]:
        status, raw, elapsed = self.request(method, path, body)
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw.decode(errors="replace")
        return status, payload, elapsed


def run_rater(
    api: Api,
    annotator_id: int,
    persona: Persona,
    *,
    project_id: int,
    schema: dict[str, Any],
    answer_key: dict[str, Any],
    input_key: str,
    key_field: str,
    time_scale: float,
    seed: int,
    max_tasks: int,
) -> dict[str, Any]:
    """One rater's session: next → think → submit / skip / exit, until the
    queue is empty, the rater is paused, or ``max_tasks``."""
    rng = random.Random(f"{seed}:{annotator_id}")
    inputs = {f["id"]: f for f in schema.get("inputs") or []}
    if input_key not in inputs:
        raise SimulationError(f"template has no input '{input_key}' (has {sorted(inputs)})")
    dimension = (schema.get("variants") or {}).get("dimension")
    extras = [
        f
        for fid, f in inputs.items()
        if fid != input_key and f.get("required") and answer_options(f)
    ]

    timings: dict[str, list[float]] = defaultdict(list)
    counts: Counter[str] = Counter()
    errors: list[dict[str, Any]] = []
    stop = "max_tasks"
    last_skipped_unit: int | None = None

    def failed(call: str, status: int, body: Any) -> None:
        counts["error"] += 1
        if len(errors) < MAX_ERRORS_KEPT:
            errors.append({"call": call, "status": status, "detail": str(body)[:300]})

    for _ in range(max_tasks):
        status, task, ms = api.call(
            "GET", f"/tasks/next?annotator={annotator_id}&project={project_id}"
        )
        timings["next"].append(ms)
        if status == 204:
            stop = "exhausted"
            break
        if status == 403:
            stop = "paused"
            break
        if status != 200:
            failed("next", status, task)
            stop = f"http {status}"
            break
        if last_skipped_unit is not None and task["unit_id"] == last_skipped_unit:
            counts["reserved_after_skip"] += 1
        last_skipped_unit = None

        think = rng.randint(*persona.latency_ms)
        if time_scale > 0:
            time.sleep(think * time_scale / 1000)
        roll = rng.random()
        action = (
            "skip"
            if roll < persona.skip_rate
            else "exit"
            if roll < persona.skip_rate + persona.exit_rate
            else "submit"
        )
        slot = task["slot_id"]
        if action != "submit":
            status, body, ms = api.call(
                "POST", f"/tasks/{slot}/skip?annotator={annotator_id}&reason={action}"
            )
            timings["skip"].append(ms)
            if status == 200:
                counts[action] += 1
            else:
                failed(action, status, body)
            last_skipped_unit = task["unit_id"]
            continue

        variant = (task.get("variant") or {}).get(dimension) if dimension else None
        item = (task.get("payload") or {}).get(key_field)
        truth = answer_key.get(str(item)) if item is not None else None
        raw = {input_key: choose_answer(persona, inputs[input_key], truth, variant, rng)}
        for field in extras:
            raw[field["id"]] = rng.choice(answer_options(field))
        status, out, ms = api.call(
            "POST",
            f"/tasks/{slot}/submit?annotator={annotator_id}",
            {"raw": raw, "latency_ms": think},
        )
        timings["submit"].append(ms)
        if status != 201:
            failed("submit", status, out)
            continue
        counts["submitted"] += 1
        if ((out or {}).get("quality") or {}).get("paused"):
            stop = "paused"
            break
    return {
        "annotator_id": annotator_id,
        "persona": persona.name,
        "stop": stop,
        "counts": dict(counts),
        "errors": errors,
        "timings": {k: v for k, v in timings.items()},
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--project", type=int, required=True)
    parser.add_argument("--raters", required=True, help="JSON from app.measure.provision --out")
    parser.add_argument("--answer-key", required=True, help="JSONL answer key")
    parser.add_argument("--key-field", required=True, help="payload field joining units to the key")
    parser.add_argument("--input", required=True, help="the template input being scored")
    parser.add_argument("--mix", required=True, help="persona:count,... given to raters in order")
    parser.add_argument("--time-scale", type=float, default=0.0, help="1.0 = real think time")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--max-tasks", type=int, default=10_000, help="per rater")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)

    raters = [r for r in json.loads(Path(args.raters).read_text()) if r.get("api_key")]
    mix = parse_mix(args.mix)
    if len(mix) > len(raters):
        raise SimulationError(f"mix needs {len(mix)} raters with keys, file has {len(raters)}")
    answer_key = parse_answer_key(
        Path(args.answer_key).read_text(encoding="utf-8"),
        key_field=args.key_field,
        input_key=args.input,
    )
    probe = Api(args.api, raters[0]["api_key"])
    status, project, _ = probe.call("GET", f"/projects/{args.project}")
    if status != 200:
        raise SimulationError(f"GET /projects/{args.project} → {status}: {project}")
    status, template, _ = probe.call("GET", f"/templates/{project['template_id']}")
    if status != 200:
        raise SimulationError(f"GET /templates/{project['template_id']} → {status}: {template}")

    assigned = list(zip(raters, mix, strict=False))
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(assigned)) as pool:
        futures = [
            pool.submit(
                run_rater,
                Api(args.api, rater["api_key"]),
                rater["annotator_id"],
                PERSONAS[persona],
                project_id=args.project,
                schema=template["schema"],
                answer_key=answer_key,
                input_key=args.input,
                key_field=args.key_field,
                time_scale=args.time_scale,
                seed=args.seed,
                max_tasks=args.max_tasks,
            )
            for rater, persona in assigned
        ]
        results = [f.result() for f in futures]
    wall = time.perf_counter() - started

    all_timings: dict[str, list[float]] = defaultdict(list)
    for result in results:
        for endpoint, values in result.pop("timings").items():
            all_timings[endpoint].extend(values)
    summary = {
        "project_id": args.project,
        "mix": args.mix,
        "seed": args.seed,
        "time_scale": args.time_scale,
        "wall_seconds": round(wall, 2),
        "personas": {name: asdict(p) for name, p in PERSONAS.items() if name in set(mix)},
        "bad_personas": sorted(BAD_PERSONAS),
        "good_personas": sorted(GOOD_PERSONAS),
        "raters": results,
        "api_latency_ms": {k: summarize(v) for k, v in sorted(all_timings.items())},
        "requests": sum(len(v) for v in all_timings.values()),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "simulation.json").write_text(json.dumps(summary, indent=2))
    planted = {str(r["annotator_id"]): r["persona"] for r in results}
    (out / "planted.json").write_text(json.dumps(planted, indent=2))
    headline = ("wall_seconds", "requests", "api_latency_ms")
    print(json.dumps({k: summary[k] for k in headline}, indent=2))
    for r in results:
        print(
            f"  annotator {r['annotator_id']:>4}  {r['persona']:<8}  {r['stop']:<10}  {r['counts']}"
        )


if __name__ == "__main__":
    main()
