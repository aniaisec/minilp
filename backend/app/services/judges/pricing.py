"""Token pricing (§7.1 budget caps, §5 ``/analytics/costs``).

Published prices move, and a hard-coded table that silently goes stale is worse
than no table: a budget cap computed from last year's prices is a cap you do not
actually have. So the resolution order is

1. ``params.price`` on the judge config — explicit, per-config, always wins;
2. the built-in table below, matched by longest model-id prefix;
3. zero — an unknown model costs nothing *and says so*, via ``priced=False``,
   which the API surfaces so "$0.00" is never mistaken for "free".

Prices are USD per **million** tokens, the unit every vendor quotes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Indicative list prices (USD / 1M tokens). Prefix-matched, longest first.
# Override per config with ``params.price = {"input": x, "output": y}``.
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4": (0.80, 4.0),
    "claude-3-5-haiku": (0.80, 4.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-opus": (15.0, 75.0),
    "claude-3-haiku": (0.25, 1.25),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.0, 8.0),
    "o4-mini": (1.10, 4.40),
    "gpt-3.5-turbo": (0.50, 1.50),
    # Local / self-hosted endpoints and the mock provider bill nothing, and that
    # is a *known* zero rather than an unknown one.
    "mock": (0.0, 0.0),
    "local": (0.0, 0.0),
}


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float
    priced: bool = True
    source: str = "table"

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return round(
            (tokens_in / 1_000_000) * self.input_per_mtok
            + (tokens_out / 1_000_000) * self.output_per_mtok,
            6,
        )


UNPRICED = Price(0.0, 0.0, priced=False, source="unknown")


def resolve_price(
    model_id: str, params: dict[str, Any] | None = None, *, provider: str | None = None
) -> Price:
    """Price for a model — explicit override, then table, then unknown."""
    override = (params or {}).get("price")
    if isinstance(override, dict) and ("input" in override or "output" in override):
        return Price(
            float(override.get("input", 0.0)),
            float(override.get("output", 0.0)),
            source="config",
        )
    if provider in ("mock", "openai_compatible"):
        return Price(0.0, 0.0, source="local")
    model = (model_id or "").lower()
    best: tuple[str, tuple[float, float]] | None = None
    for prefix, price in PRICE_TABLE.items():
        if model.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, price)
    if best is None:
        return UNPRICED
    return Price(best[1][0], best[1][1], source=f"table:{best[0]}")


def estimate_cost(
    model_id: str,
    tokens_in: int,
    tokens_out: int,
    params: dict[str, Any] | None = None,
    *,
    provider: str | None = None,
) -> float:
    return resolve_price(model_id, params, provider=provider).cost(tokens_in, tokens_out)
