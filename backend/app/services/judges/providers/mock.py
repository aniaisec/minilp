"""The mock provider — a real provider class, not a test double bolted on.

It ships in ``app/`` rather than ``tests/`` on purpose. Three things need a judge
that answers instantly, deterministically and for free:

1. the M7 acceptance suite ("a mock-provider judge fills slots respecting balance
   and golds") — which must assert on *what* was answered, so the answer has to
   be reproducible;
2. ``docker compose up`` demo, where requiring an API key to see the judge
   feature at all would be a poor first five minutes;
3. anyone evaluating whether the orchestrator does what it claims before pointing
   it at a paid endpoint.

Determinism comes from hashing the prompt, so the same unit always gets the same
answer, and different units get different ones. That gives the suite a judge with
a *stable but non-trivial* answer distribution — enough to exercise agreement,
golds and bias without a network.

Config knobs (``params.mock``): ``answers`` pins per-input answers, ``confidence``
sets the reported confidence, ``fail_every`` makes every Nth call raise (so retry
and error paths are testable), ``latency_ms`` simulates slowness.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.services.judges.providers.base import (
    JudgeRequest,
    Provider,
    ProviderError,
    ProviderResponse,
)

# The prompt tells the judge to answer in JSON under these keys (see prompt.py).
_FIELD_RE = re.compile(r'^\s*-\s*"(?P<id>[A-Za-z_][A-Za-z0-9_]*)"\s*\((?P<type>[a-z_]+)\)', re.M)
_OPTIONS_RE = re.compile(r"one of:\s*(?P<opts>\[.*?\])", re.S)


def _digest(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16)


class MockProvider(Provider):
    """Deterministic, free, offline. Same contract as the paid ones."""

    name = "mock"
    requires_api_key = False
    default_base_url = "mock://local"

    def complete(self, request: JudgeRequest) -> ProviderResponse:
        cfg: dict[str, Any] = self.params.get("mock") or {}

        fail_every = int(cfg.get("fail_every") or 0)
        self._calls = getattr(self, "_calls", 0) + 1
        if fail_every and self._calls % fail_every == 0:
            raise ProviderError(
                f"mock provider: simulated failure on call {self._calls}",
                status=500,
                retryable=bool(cfg.get("retryable", True)),
            )

        seed = _digest(request.prompt)
        answers: dict[str, Any] = {}
        for match in _FIELD_RE.finditer(request.prompt):
            field_id = match.group("id")
            answers[field_id] = self._answer_for(
                field_id, match.group("type"), request.prompt[match.end() : match.end() + 400], seed
            )
        answers.update(cfg.get("answers") or {})

        body = {
            "answers": answers,
            "confidence": float(cfg.get("confidence", 0.6 + (seed % 40) / 100.0)),
            "reasoning": cfg.get(
                "reasoning", "Deterministic mock judgment derived from the prompt hash."
            ),
        }
        text = json.dumps(body)
        return ProviderResponse(
            text=text,
            tokens_in=request.estimated_tokens_in(),
            tokens_out=max(1, len(text) // 4),
            model_id=self.model_id,
            raw={"provider": "mock", "call": self._calls},
        )

    @staticmethod
    def _answer_for(field_id: str, ftype: str, tail: str, seed: int) -> Any:
        """Pick a plausible answer of the right value shape (§2.3)."""
        options_match = _OPTIONS_RE.search(tail)
        options: list[str] = []
        if options_match:
            try:
                options = [str(o) for o in json.loads(options_match.group("opts"))]
            except (ValueError, TypeError):
                options = []
        pick = _digest(f"{seed}:{field_id}")
        if options:
            if ftype in ("checkbox", "multiselect", "tags", "ranking"):
                return [options[pick % len(options)]]
            return options[pick % len(options)]
        if ftype in ("likert", "rating"):
            return 1 + pick % 5
        if ftype in ("number", "slider"):
            return float(pick % 100)
        if ftype == "boolean":
            return bool(pick % 2)
        if ftype == "date":
            return "2026-01-01"
        if ftype == "datetime":
            return "2026-01-01T12:00"
        return f"mock-{pick % 1000}"
