"""The provider contract (§7.1) — one small class per LLM API.

Deliberately tiny: a provider takes an assembled prompt and returns text plus
token counts. Everything else in M7 — prompt assembly, parsing, caching, budget,
retries — lives *outside* the provider, because that is what keeps "add a
provider" a 40-line job and keeps every guardrail identical across vendors.

No vendor SDKs. Each provider is a thin ``httpx`` call against a documented HTTP
endpoint, which is also what makes the OpenAI-compatible class useful: a local
vLLM / llama.cpp / Ollama server, or a fine-tuned checkpoint from the M9 loop, is
the same class with a different ``base_url``.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Rough characters-per-token used only for *estimates* (dry-run, §7.1). Real
# accounting always uses the provider's reported usage; this is for telling an
# admin "about $0.40" before they spend anything.
CHARS_PER_TOKEN = 4.0


@dataclass(frozen=True)
class JudgeRequest:
    """What a provider is asked to do — vendor-neutral."""

    prompt: str
    model_id: str
    system: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def estimated_tokens_in(self) -> int:
        chars = len(self.prompt) + len(self.system or "")
        return max(1, int(chars / CHARS_PER_TOKEN))


@dataclass(frozen=True)
class ProviderResponse:
    """What came back. ``confidence`` is only set when the provider exposes
    logprobs; otherwise the judge is asked to state its confidence in-band and
    the parser reads it from the JSON (§7.1)."""

    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    model_id: str = ""
    confidence: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    """A provider call failed.

    ``retryable`` separates "the network hiccuped / you are rate limited" from
    "your request is malformed" — retrying the latter just burns the backoff
    budget and delays a real error message.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class RateLimited(ProviderError):
    def __init__(self, message: str = "rate limited", *, status: int | None = 429) -> None:
        super().__init__(message, status=status, retryable=True)


class Provider(ABC):
    """Base class. Subclasses implement exactly one method."""

    name: str = "base"
    # Whether the provider needs credentials — the mock does not, which is what
    # lets the demo and the whole test suite run with no keys anywhere.
    requires_api_key: bool = True

    def __init__(
        self,
        *,
        model_id: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.model_id = model_id
        self.api_key = api_key
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self.timeout = timeout
        self.params = params or {}

    default_base_url: str = ""

    @abstractmethod
    def complete(self, request: JudgeRequest) -> ProviderResponse:
        """Run one completion, or raise ``ProviderError``."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} model={self.model_id!r}>"


# --- guardrails around any provider (§7.1) ----------------------------------


class RateLimiter:
    """Minimum-interval limiter — the smallest thing that actually works.

    A token bucket would let a burst through, which is precisely the shape of
    call pattern that trips vendor per-minute limits on the first ten units of a
    run. Spacing calls evenly costs nothing on a batch job and never bursts.
    ``requests_per_minute=0`` disables it.
    """

    def __init__(
        self,
        requests_per_minute: float = 0.0,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = self._clock()
        if self._last is not None:
            gap = self.min_interval - (now - self._last)
            if gap > 0:
                self._sleep(gap)
                now = self._clock()
        self._last = now


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with a cap. ``attempts=1`` means "no retries"."""

    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0

    def delay_for(self, attempt: int) -> float:
        return min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))


def call_with_retries(
    provider: Provider,
    request: JudgeRequest,
    *,
    policy: RetryPolicy | None = None,
    limiter: RateLimiter | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ProviderResponse:
    """Call a provider, retrying *retryable* failures with backoff (§7.1)."""
    policy = policy or RetryPolicy()
    last: ProviderError | None = None
    for attempt in range(1, max(1, policy.attempts) + 1):
        if limiter is not None:
            limiter.wait()
        try:
            return provider.complete(request)
        except ProviderError as e:
            last = e
            if not e.retryable or attempt >= policy.attempts:
                raise
            sleep(policy.delay_for(attempt))
    raise last or ProviderError("provider call failed")  # pragma: no cover
