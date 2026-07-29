"""The three HTTP providers: Anthropic, OpenAI, and OpenAI-compatible (§7.1).

All three are the same shape — POST JSON, read text and usage back — so they
share a request helper and differ only in URL, auth header, body and response
path. Keeping them in one module makes that symmetry visible; splitting them into
three files mostly duplicates the error handling.

``httpx`` is imported lazily so the rest of MiniLP (and the whole test suite,
which drives the mock provider) has no hard dependency on it.
"""

from __future__ import annotations

from typing import Any

from app.services.judges.providers.base import (
    JudgeRequest,
    Provider,
    ProviderError,
    ProviderResponse,
    RateLimited,
)

# Statuses worth trying again: rate limits and transient server-side faults.
RETRYABLE_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})


def _post(url: str, *, headers: dict[str, str], body: dict[str, Any], timeout: float) -> dict:
    try:
        import httpx
    except ImportError as e:  # pragma: no cover - environment-dependent
        raise ProviderError(
            "httpx is required for live providers; install it or use provider='mock'"
        ) from e

    try:
        response = httpx.post(url, headers=headers, json=body, timeout=timeout)
    except Exception as e:  # network-level: always worth one more try
        raise ProviderError(f"request to {url} failed: {e}", retryable=True) from e

    if response.status_code == 429:
        raise RateLimited(f"{url} rate limited: {response.text[:300]}")
    if response.status_code >= 400:
        raise ProviderError(
            f"{url} returned {response.status_code}: {response.text[:300]}",
            status=response.status_code,
            retryable=response.status_code in RETRYABLE_STATUSES,
        )
    try:
        return response.json()
    except ValueError as e:
        raise ProviderError(f"{url} returned non-JSON body") from e


class AnthropicProvider(Provider):
    """Anthropic Messages API."""

    name = "anthropic"
    default_base_url = "https://api.anthropic.com"
    api_version = "2023-06-01"

    def complete(self, request: JudgeRequest) -> ProviderResponse:
        if not self.api_key:
            raise ProviderError("anthropic provider requires an API key")
        body: dict[str, Any] = {
            "model": request.model_id,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            body["system"] = request.system
        body.update(request.extra)

        data = _post(
            f"{self.base_url}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.api_version,
                "content-type": "application/json",
            },
            body=body,
            timeout=self.timeout,
        )
        parts = data.get("content") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        usage = data.get("usage") or {}
        return ProviderResponse(
            text=text,
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
            model_id=data.get("model") or request.model_id,
            raw={"stop_reason": data.get("stop_reason")},
        )


class OpenAIProvider(Provider):
    """OpenAI Chat Completions API."""

    name = "openai"
    default_base_url = "https://api.openai.com/v1"

    def complete(self, request: JudgeRequest) -> ProviderResponse:
        if not self.api_key and self.requires_api_key:
            raise ProviderError(f"{self.name} provider requires an API key")
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        body: dict[str, Any] = {
            "model": request.model_id,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        body.update(request.extra)

        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"

        data = _post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            body=body,
            timeout=self.timeout,
        )
        choices = data.get("choices") or []
        text = ""
        if choices:
            text = ((choices[0] or {}).get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        return ProviderResponse(
            text=text,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            model_id=data.get("model") or request.model_id,
            raw={"finish_reason": (choices[0] or {}).get("finish_reason") if choices else None},
        )


class OpenAICompatibleProvider(OpenAIProvider):
    """Any server speaking the OpenAI Chat Completions shape.

    This is the class §7.1 leans on for M9: a fine-tuned checkpoint re-enrolled as
    a judge is *this provider, a different base_url* — no new code. Local servers
    (vLLM, llama.cpp, Ollama, LM Studio) usually want no key at all, so unlike its
    parent it does not insist on one.
    """

    name = "openai_compatible"
    requires_api_key = False
    default_base_url = "http://localhost:8000/v1"
