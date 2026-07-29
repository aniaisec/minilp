"""The judge orchestrator (§7.1) — the loop that turns a model into an annotator.

The whole design of M7 is in one line of this file: it calls ``next_task`` and
``submit_label``, the same two functions the annotation UI calls. Nothing here
knows about variant balance, gold injection, annotator-unit exclusion, lease
expiry, canonicalization, gold grading, reputation or consensus growth — all of
that already happens, correctly, for whoever pulls work. Enrolling a judge as a
``kind=model`` annotator is what makes it inherit the lot (principle 2).

What *is* judge-specific, and therefore lives here:

- **assemble → call → parse → submit**, with the cache checked before the call;
- **budget checked before and after each call**, hard-stopping the run and firing
  ``budget.cap_reached`` once (§7.3);
- **dry-run**, which assembles the real prompt, prices it, and releases the slot —
  an estimate that costs nothing and can be wrong only about the *output* length;
- **failure handling**: a provider error or an unparseable reply releases the
  lease (``skip_task``) so the unit returns to the pool with its variant intact.
  A judge that could not answer must leave no trace but a run-report line.

A ``judge_runs`` row is written however the run ends — exhausted, capped,
limited or broken. A run that died is more interesting than one that vanished.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import JudgeConfig, JudgeRun, Project, Template, Unit
from app.services.assignment import AssignmentError, next_task, skip_task, submit_label
from app.services.judges.budget import check_budget, judge_spend
from app.services.judges.cache import CacheKey, lookup, store
from app.services.judges.configs import JudgeError, resolve_enrollment
from app.services.judges.parsing import ParseError, parse_response
from app.services.judges.pricing import estimate_cost, resolve_price
from app.services.judges.prompt import assemble_prompt, variant_key
from app.services.judges.providers import (
    JudgeRequest,
    Provider,
    ProviderError,
    RateLimiter,
    RetryPolicy,
    build_provider,
    call_with_retries,
)
from app.services.webhooks import Sender, emit

# Assumed reply length when pricing a dry run. Judge replies are a small JSON
# object plus a sentence of reasoning; over-estimating output tokens makes the
# estimate conservative, which is the right direction for a spending guardrail.
DRY_RUN_OUTPUT_TOKENS = 220

# How many slots a run will take before stopping, when no explicit limit is
# given. A bounded default keeps "click Run" from turning into an unbounded spend
# on a project with 50k open slots.
DEFAULT_LIMIT = 100


@dataclass
class RunResult:
    """A run's report — mirrors the ``judge_runs`` row, plus per-unit errors."""

    project_id: int
    judge_config_id: int
    annotator_id: int | None = None
    run_id: int | None = None
    dry_run: bool = False
    status: str = "completed"
    stopped_reason: str | None = None
    slots_attempted: int = 0
    labels_written: int = 0
    cache_hits: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    estimated_cost_usd: float | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    budget: dict[str, Any] | None = None
    webhooks_fired: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "judge_config_id": self.judge_config_id,
            "annotator_id": self.annotator_id,
            "dry_run": self.dry_run,
            "status": self.status,
            "stopped_reason": self.stopped_reason,
            "slots_attempted": self.slots_attempted,
            "labels_written": self.labels_written,
            "cache_hits": self.cache_hits,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            "estimated_cost_usd": (
                round(self.estimated_cost_usd, 6) if self.estimated_cost_usd is not None else None
            ),
            "errors": self.errors,
            "budget": self.budget,
            "webhooks_fired": self.webhooks_fired,
        }


def _required_ids(schema: dict[str, Any]) -> list[str]:
    return [f["id"] for f in schema.get("inputs") or [] if f.get("required") and f.get("id")]


def run_judge(
    db: Session,
    project_id: int,
    judge_config_id: int,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    provider: Provider | None = None,
    sender: Sender | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
    record_run: bool = True,
) -> RunResult:
    """Drive one judge over a project's open slots (§5 ``judges:run``).

    ``provider`` is injectable so the acceptance suite runs a real orchestration
    against a deterministic judge with no network; in production it is built from
    the config by ``build_provider``.
    """
    now = now or datetime.now(UTC)
    project = db.get(Project, project_id)
    if project is None:
        raise JudgeError(f"project {project_id} not found", status=404)
    config = db.get(JudgeConfig, judge_config_id)
    if config is None:
        raise JudgeError(f"judge config {judge_config_id} not found", status=404)
    template = db.get(Template, project.template_id)
    if template is None:
        raise JudgeError(f"project {project_id} has no template", status=422)

    annotator = resolve_enrollment(db, project, judge_config_id)
    params = config.params or {}
    result = RunResult(
        project_id=project_id,
        judge_config_id=judge_config_id,
        annotator_id=annotator.id,
        dry_run=dry_run,
        budget=config.budget,
    )
    if dry_run:
        result.estimated_cost_usd = 0.0

    if provider is None:
        try:
            provider = build_provider(config.provider, config.model_id, params)
        except ProviderError as e:
            raise JudgeError(str(e), status=422) from e

    price = resolve_price(config.model_id, params, provider=config.provider)
    retry = RetryPolicy(
        attempts=int(params.get("retries", 3)),
        base_delay=float(params.get("retry_base_delay", 0.5)),
    )
    limiter = RateLimiter(float(params.get("requests_per_minute", 0) or 0), sleep=sleep)
    max_slots = DEFAULT_LIMIT if limit is None else max(0, int(limit))
    required = _required_ids(template.schema)

    # Units this run has already taken a swing at. Releasing a lease reopens the
    # slot for everyone *including us*, so without this a judge that fails to
    # parse one unit would be handed it again on the very next pull, forever.
    attempted: set[int] = set()

    spend = judge_spend(db, project_id, annotator.id, now=now)
    status = check_budget(config.budget, spend)
    if not status.ok:
        result.status = "stopped"
        result.stopped_reason = status.reason
        result.webhooks_fired = _fire_budget_webhook(
            db, project, config, annotator.id, status.detail, sender=sender, sleep=sleep
        )
        return _finish(db, result, record_run, now)

    while result.slots_attempted < max_slots:
        try:
            slot = next_task(db, annotator.id, project_id, now=now, exclude_units=attempted)
        except AssignmentError as e:
            result.status = "stopped"
            result.stopped_reason = "provider_error" if e.status >= 500 else "exhausted"
            result.errors.append({"stage": "next", "error": str(e)})
            break
        if slot is None:
            result.stopped_reason = "exhausted"
            break

        result.slots_attempted += 1
        attempted.add(slot.unit_id)
        unit = db.get(Unit, slot.unit_id)
        if unit is None:  # pragma: no cover - FK makes this unreachable
            skip_task(db, slot.id, annotator.id)
            continue

        prompt = assemble_prompt(
            template.schema,
            unit.payload or {},
            guidelines_md=project.guidelines_md,
            variant=slot.variant,
            prompt_template=config.prompt_template,
            system=params.get("system"),
        )
        key = CacheKey(
            judge_config_id=config.id,
            prompt_version=config.prompt_version,
            unit_id=unit.id,
            variant_key=variant_key(template.schema, slot.variant),
        )
        digest = prompt.digest()

        # --- dry run: price it, release the slot, spend nothing ---------------
        if dry_run:
            cached = lookup(db, key, digest)
            tokens_in = cached.tokens_in if cached else _estimate_in(prompt)
            tokens_out = cached.tokens_out if cached else DRY_RUN_OUTPUT_TOKENS
            if cached is not None:
                result.cache_hits += 1
            else:
                result.tokens_in += tokens_in
                result.tokens_out += tokens_out
                result.estimated_cost_usd = (result.estimated_cost_usd or 0.0) + price.cost(
                    tokens_in, tokens_out
                )
            skip_task(db, slot.id, annotator.id)
            continue

        # --- cache, then call ------------------------------------------------
        cached = lookup(db, key, digest)
        call_started = time.monotonic()
        if cached is not None:
            text, tokens_in, tokens_out, cost, hit = (
                cached.response_text,
                cached.tokens_in,
                cached.tokens_out,
                0.0,
                True,
            )
            result.cache_hits += 1
        else:
            request = JudgeRequest(
                prompt=prompt.user,
                model_id=config.model_id,
                system=prompt.system,
                max_tokens=int(params.get("max_tokens", 1024)),
                temperature=float(params.get("temperature", 0.0)),
                extra=params.get("extra") or {},
            )
            try:
                response = call_with_retries(
                    provider, request, policy=retry, limiter=limiter, sleep=sleep
                )
            except ProviderError as e:
                result.errors.append(
                    {"stage": "provider", "unit_id": unit.id, "error": str(e)[:400]}
                )
                _release(db, slot.id, annotator.id)
                if _fatal(e):
                    result.status = "stopped"
                    result.stopped_reason = "provider_error"
                    break
                continue
            text = response.text
            tokens_in = response.tokens_in or _estimate_in(prompt)
            tokens_out = response.tokens_out or max(1, len(text) // 4)
            cost = estimate_cost(
                config.model_id, tokens_in, tokens_out, params, provider=config.provider
            )
            hit = False

        try:
            parsed = parse_response(text, prompt.field_ids, required_ids=required)
        except ParseError as e:
            result.errors.append({"stage": "parse", "unit_id": unit.id, "error": str(e)[:400]})
            _release(db, slot.id, annotator.id)
            continue

        latency_ms = int((time.monotonic() - call_started) * 1000)
        try:
            submit_label(
                db,
                slot.id,
                annotator.id,
                raw=parsed.raw,
                confidence=parsed.confidence,
                reasoning=parsed.reasoning,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                cache_hit=hit,
            )
        except AssignmentError as e:
            result.errors.append({"stage": "submit", "unit_id": unit.id, "error": str(e)})
            continue

        result.labels_written += 1
        result.tokens_in += tokens_in
        result.tokens_out += tokens_out
        result.cost_usd += cost
        if parsed.missing_fields:
            result.errors.append(
                {
                    "stage": "parse",
                    "unit_id": unit.id,
                    "error": f"missing required fields {parsed.missing_fields}",
                    "level": "warning",
                }
            )

        if not hit:
            store(
                db,
                key,
                prompt_hash=digest,
                response_text=text,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
            )

        # --- re-check the cap with what we just spent ------------------------
        spend = spend.plus(cost=cost, tokens=tokens_in + tokens_out, labels=1, hits=1 if hit else 0)
        status = check_budget(config.budget, spend)
        if not status.ok:
            result.status = "stopped"
            result.stopped_reason = status.reason
            result.webhooks_fired = _fire_budget_webhook(
                db, project, config, annotator.id, status.detail, sender=sender, sleep=sleep
            )
            break
    else:
        result.stopped_reason = result.stopped_reason or "limit"

    return _finish(db, result, record_run, now)


def _estimate_in(prompt: Any) -> int:
    from app.services.judges.providers.base import CHARS_PER_TOKEN

    return max(1, int((len(prompt.user) + len(prompt.system or "")) / CHARS_PER_TOKEN))


def _fatal(error: ProviderError) -> bool:
    """Stop the whole run, or just this unit?

    A 401/404 is a configuration mistake — every subsequent call will fail the
    same way, so continuing would produce N identical errors and N released
    slots. A 5xx that survived the retry policy is treated the same way: the
    endpoint is having a bad time and hammering it is not neighbourly.
    """
    return error.status in (400, 401, 403, 404) or error.retryable


def _release(db: Session, slot_id: int, annotator_id: int) -> None:
    """Return an unanswered slot to the pool, variant intact (§2.7)."""
    with contextlib.suppress(AssignmentError):  # the lease may already be gone
        skip_task(db, slot_id, annotator_id)


def _fire_budget_webhook(
    db: Session,
    project: Project,
    config: JudgeConfig,
    annotator_id: int,
    detail: dict[str, Any] | None,
    *,
    sender: Sender | None,
    sleep: Callable[[float], None],
) -> int:
    deliveries = emit(
        db,
        "budget.cap_reached",
        project_id=project.id,
        payload={
            "judge_config_id": config.id,
            "judge": f"{config.name} v{config.prompt_version}",
            "annotator_id": annotator_id,
            "metric": detail or {},
        },
        sender=sender,
        sleep=sleep,
    )
    return len(deliveries)


def _finish(db: Session, result: RunResult, record: bool, now: datetime) -> RunResult:
    if result.stopped_reason and result.stopped_reason.startswith("budget"):
        result.status = "stopped"
    if not record:
        return result
    run = JudgeRun(
        project_id=result.project_id,
        judge_config_id=result.judge_config_id,
        annotator_id=result.annotator_id,
        dry_run=result.dry_run,
        status=result.status,
        stopped_reason=result.stopped_reason,
        slots_attempted=result.slots_attempted,
        labels_written=result.labels_written,
        cache_hits=result.cache_hits,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=round(result.cost_usd, 6),
        estimated_cost_usd=(
            round(result.estimated_cost_usd, 6) if result.estimated_cost_usd is not None else None
        ),
        errors=result.errors or None,
        finished_at=now,
    )
    db.add(run)
    db.flush()
    result.run_id = run.id
    return result


def dry_run_estimate(
    db: Session,
    project_id: int,
    judge_config_id: int,
    *,
    limit: int | None = None,
    provider: Provider | None = None,
) -> RunResult:
    """Cost estimate for a run, in the run's own units (§7.1 dry-run)."""
    return run_judge(db, project_id, judge_config_id, limit=limit, dry_run=True, provider=provider)
