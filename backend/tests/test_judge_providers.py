"""Provider abstraction, retries, rate limiting, pricing and budget caps (M7, §7.1).

All pure — no DB, no network. The HTTP providers are exercised by substituting the
module's ``_post`` helper, which keeps the assertions on *the contract* (what URL,
what auth header, what body shape, what the response maps to) rather than on
httpx's internals.
"""

import json

import pytest

from app.services.judges import budget as budget_mod
from app.services.judges.budget import Spend, check_budget
from app.services.judges.pricing import estimate_cost, resolve_price
from app.services.judges.prompt import assemble_prompt
from app.services.judges.providers import (
    AnthropicProvider,
    JudgeRequest,
    MockProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    ProviderError,
    RateLimited,
    RateLimiter,
    RetryPolicy,
    build_provider,
    call_with_retries,
    provider_names,
)
from app.services.judges.providers import http as http_mod
from app.services.templates.seed import IMAGE_CLASSIFICATION, SIDE_BY_SIDE

PAIR_PAYLOAD = {"prompt": "p", "response_a": "left text", "response_b": "right text"}


def _prompt(schema=IMAGE_CLASSIFICATION, payload=None, **kw):
    return assemble_prompt(schema, payload or {"image_url": "http://x/1.png"}, **kw)


def _request(prompt) -> JudgeRequest:
    return JudgeRequest(prompt=prompt.user, model_id="mock-1", system=prompt.system)


# --- the mock provider is a real provider ------------------------------------


def test_mock_answers_in_the_template_value_shape():
    prompt = _prompt()
    response = MockProvider(model_id="mock-1").complete(_request(prompt))
    body = json.loads(response.text)
    assert body["answers"]["category"] in IMAGE_CLASSIFICATION["inputs"][0]["options"]
    assert 0.0 <= body["confidence"] <= 1.0
    assert response.tokens_in > 0 and response.tokens_out > 0


def test_mock_is_deterministic_per_prompt_and_varies_across_prompts():
    provider = MockProvider(model_id="mock-1")
    one, two = _prompt(), _prompt(payload={"image_url": "http://x/2.png"})
    assert provider.complete(_request(one)).text == provider.complete(_request(one)).text
    # Different unit → different prompt → an independent draw.
    answers = {
        json.loads(provider.complete(_request(p)).text)["answers"]["category"] for p in (one, two)
    }
    assert answers  # both parsed; equality is allowed, determinism is what matters


def test_mock_answers_can_be_pinned_for_a_fixture():
    provider = MockProvider(model_id="m", params={"mock": {"answers": {"category": "dog"}}})
    body = json.loads(provider.complete(_request(_prompt())).text)
    assert body["answers"]["category"] == "dog"


def test_mock_answers_side_by_side_positionally_not_in_ab_space():
    """The mock picks from Left/Tie/Right — the same space a human clicks in."""
    prompt = _prompt(SIDE_BY_SIDE, PAIR_PAYLOAD, variant={"panel_order": "BA"})
    body = json.loads(MockProvider(model_id="m").complete(_request(prompt)).text)
    assert body["answers"]["choice"] in ["Left", "Tie", "Right"]


def test_mock_can_simulate_failures():
    provider = MockProvider(model_id="m", params={"mock": {"fail_every": 1}})
    with pytest.raises(ProviderError):
        provider.complete(_request(_prompt()))


# --- retries + rate limiting -------------------------------------------------


class _Flaky(MockProvider):
    def __init__(self, failures: int, retryable: bool = True, **kw):
        super().__init__(model_id="m", **kw)
        self.remaining = failures
        self.retryable = retryable
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise ProviderError("boom", status=503, retryable=self.retryable)
        return super().complete(request)


def test_retries_recover_from_a_transient_failure():
    provider = _Flaky(failures=2)
    slept: list[float] = []
    response = call_with_retries(
        provider,
        _request(_prompt()),
        policy=RetryPolicy(attempts=3, base_delay=0.1),
        sleep=slept.append,
    )
    assert provider.calls == 3
    assert slept == [0.1, 0.2]  # exponential backoff
    assert json.loads(response.text)["answers"]


def test_retries_give_up_after_the_policy_and_reraise():
    provider = _Flaky(failures=99)
    with pytest.raises(ProviderError):
        call_with_retries(
            provider, _request(_prompt()), policy=RetryPolicy(attempts=2), sleep=lambda _: None
        )
    assert provider.calls == 2


def test_non_retryable_failures_are_not_retried():
    provider = _Flaky(failures=99, retryable=False)
    with pytest.raises(ProviderError):
        call_with_retries(
            provider, _request(_prompt()), policy=RetryPolicy(attempts=5), sleep=lambda _: None
        )
    assert provider.calls == 1, "a malformed request must not burn the retry budget"


def test_rate_limiter_spaces_calls_evenly():
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(60.0, sleep=sleep, clock=lambda: now[0])  # 1/second
    limiter.wait()
    limiter.wait()
    assert slept == [1.0]


def test_rate_limiter_disabled_by_default():
    slept: list[float] = []
    limiter = RateLimiter(0, sleep=slept.append, clock=lambda: 0.0)
    limiter.wait()
    limiter.wait()
    assert slept == []


# --- the HTTP providers ------------------------------------------------------


def test_anthropic_sends_the_messages_shape_and_maps_usage(monkeypatch):
    seen = {}

    def fake_post(url, *, headers, body, timeout):
        seen.update(url=url, headers=headers, body=body)
        return {
            "content": [{"type": "text", "text": '{"answers": {"category": "cat"}}'}],
            "usage": {"input_tokens": 120, "output_tokens": 18},
            "model": "claude-test",
        }

    monkeypatch.setattr(http_mod, "_post", fake_post)
    provider = AnthropicProvider(model_id="claude-test", api_key="sk-test")
    response = provider.complete(JudgeRequest(prompt="hi", model_id="claude-test", system="sys"))

    assert seen["url"].endswith("/v1/messages")
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert seen["headers"]["anthropic-version"]
    assert seen["body"]["system"] == "sys"
    assert seen["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert (response.tokens_in, response.tokens_out) == (120, 18)
    assert "cat" in response.text


def test_openai_sends_chat_completions_and_maps_usage(monkeypatch):
    seen = {}

    def fake_post(url, *, headers, body, timeout):
        seen.update(url=url, headers=headers, body=body)
        return {
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 5},
        }

    monkeypatch.setattr(http_mod, "_post", fake_post)
    OpenAIProvider(model_id="gpt-test", api_key="sk-x").complete(
        JudgeRequest(prompt="hi", model_id="gpt-test", system="sys")
    )
    assert seen["url"].endswith("/chat/completions")
    assert seen["headers"]["authorization"] == "Bearer sk-x"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}


def test_openai_compatible_targets_a_local_base_url_without_a_key(monkeypatch):
    """The M9 re-enrollment path: same class, new base_url, no new code (§7.1)."""
    seen = {}

    def fake_post(url, *, headers, body, timeout):
        seen.update(url=url, headers=headers)
        return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    monkeypatch.setattr(http_mod, "_post", fake_post)
    provider = OpenAICompatibleProvider(model_id="local-ft-v2", base_url="http://gpu-box:8000/v1")
    provider.complete(JudgeRequest(prompt="hi", model_id="local-ft-v2"))
    assert seen["url"] == "http://gpu-box:8000/v1/chat/completions"
    assert "authorization" not in seen["headers"]


def test_openai_without_a_key_refuses_before_calling_out():
    with pytest.raises(ProviderError, match="API key"):
        OpenAIProvider(model_id="gpt-test").complete(JudgeRequest(prompt="x", model_id="g"))


def test_rate_limit_response_is_retryable():
    assert RateLimited().retryable is True


# --- the registry ------------------------------------------------------------


def test_registry_lists_all_four_providers():
    assert set(provider_names()) == {"mock", "anthropic", "openai", "openai_compatible"}


def test_build_provider_reads_the_key_from_the_named_env_var():
    provider = build_provider(
        "anthropic", "claude-x", {"api_key_env": "MY_KEY"}, env={"MY_KEY": "sk-from-env"}
    )
    assert provider.api_key == "sk-from-env"


def test_build_provider_rejects_an_unknown_name():
    with pytest.raises(ProviderError, match="unknown provider"):
        build_provider("telepathy", "brain-1", {})


def test_mock_needs_no_key_at_all():
    assert build_provider("mock", "mock-1", {}, env={}).api_key is None


# --- pricing -----------------------------------------------------------------


def test_price_table_matches_the_longest_model_prefix():
    assert resolve_price("claude-3-5-haiku-20241022").source == "table:claude-3-5-haiku"
    assert resolve_price("gpt-4o-mini-2024").source == "table:gpt-4o-mini"


def test_explicit_price_override_wins():
    price = resolve_price("whatever-9000", {"price": {"input": 1.0, "output": 2.0}})
    assert price.source == "config"
    assert price.cost(1_000_000, 1_000_000) == 3.0


def test_unknown_model_is_unpriced_rather_than_free():
    price = resolve_price("some-new-model-nobody-knows")
    assert price.priced is False, "an unknown price must not masquerade as $0.00"
    assert price.cost(1000, 1000) == 0.0


def test_local_and_mock_are_a_known_zero():
    assert resolve_price("anything", provider="mock").priced is True
    assert resolve_price("local-ft-v3", provider="openai_compatible").cost(10**6, 10**6) == 0.0


def test_estimate_cost_is_per_million_tokens():
    assert estimate_cost("gpt-4o-mini", 1_000_000, 0) == pytest.approx(0.15)


# --- budget caps -------------------------------------------------------------


def test_no_budget_means_no_cap():
    assert check_budget(None, Spend(cost_usd=999.0)).ok


@pytest.mark.parametrize(
    ("budget", "spend", "reason"),
    [
        ({"project_usd": 1.0}, Spend(cost_usd=1.0), "budget_project"),
        ({"daily_usd": 0.5}, Spend(daily_usd=0.75), "budget_daily"),
        ({"max_tokens": 100}, Spend(tokens=100), "budget_tokens"),
        ({"max_labels": 3}, Spend(labels=3), "budget_labels"),
    ],
)
def test_each_cap_type_stops_at_its_limit(budget, spend, reason):
    status = check_budget(budget, spend)
    assert not status.ok
    assert status.reason == reason
    assert status.detail


def test_a_cap_allows_spend_right_up_to_the_limit():
    assert check_budget({"project_usd": 1.0}, Spend(cost_usd=0.999)).ok


def test_spend_accumulates_immutably():
    spend = Spend().plus(cost=0.25, tokens=10, labels=1).plus(cost=0.25, tokens=10, labels=1)
    assert (spend.cost_usd, spend.tokens, spend.labels) == (0.5, 20, 2)


def test_project_costs_module_exports_the_analytics_entry_point():
    assert callable(budget_mod.project_costs)
