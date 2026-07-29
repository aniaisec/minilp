"""Provider registry (§7.1) — name → class, plus construction from a JudgeConfig.

Adding a provider is: write the class, add one line to ``PROVIDERS``. That is the
whole extensibility story for the model side, mirroring §2.6 on the template side.

API keys are never stored in the database. A judge config names an *environment
variable* (``params.api_key_env``, defaulting to a per-provider convention) and the
key is read at call time — so an exported judge-config bundle (M10) is shareable
without leaking anyone's credentials.
"""

from __future__ import annotations

import os
from typing import Any

from app.services.judges.providers.base import (
    CHARS_PER_TOKEN,
    JudgeRequest,
    Provider,
    ProviderError,
    ProviderResponse,
    RateLimited,
    RateLimiter,
    RetryPolicy,
    call_with_retries,
)
from app.services.judges.providers.http import (
    AnthropicProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
)
from app.services.judges.providers.mock import MockProvider

PROVIDERS: dict[str, type[Provider]] = {
    MockProvider.name: MockProvider,
    AnthropicProvider.name: AnthropicProvider,
    OpenAIProvider.name: OpenAIProvider,
    OpenAICompatibleProvider.name: OpenAICompatibleProvider,
}

DEFAULT_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai_compatible": "OPENAI_COMPATIBLE_API_KEY",
}


def provider_names() -> list[str]:
    return sorted(PROVIDERS)


def build_provider(
    provider: str,
    model_id: str,
    params: dict[str, Any] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> Provider:
    """Construct a provider from the fields of a judge config."""
    cls = PROVIDERS.get(provider)
    if cls is None:
        raise ProviderError(f"unknown provider '{provider}' (known: {', '.join(provider_names())})")
    params = params or {}
    environ = env if env is not None else os.environ
    key_env = params.get("api_key_env") or DEFAULT_KEY_ENV.get(provider)
    api_key = environ.get(key_env) if key_env else None
    return cls(
        model_id=model_id,
        api_key=api_key,
        base_url=params.get("base_url"),
        timeout=float(params.get("timeout", 60.0)),
        params=params,
    )


__all__ = [
    "CHARS_PER_TOKEN",
    "DEFAULT_KEY_ENV",
    "PROVIDERS",
    "AnthropicProvider",
    "JudgeRequest",
    "MockProvider",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "Provider",
    "ProviderError",
    "ProviderResponse",
    "RateLimited",
    "RateLimiter",
    "RetryPolicy",
    "build_provider",
    "call_with_retries",
    "provider_names",
]
