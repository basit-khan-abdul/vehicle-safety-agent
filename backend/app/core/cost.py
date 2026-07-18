"""Token → USD cost estimation for the per-request budget cap.

Prices are USD per 1,000,000 tokens, ``(input, output)``. Anthropic publishes
these per model; keep this table in step with the models the agent may run.
"""

from __future__ import annotations

# USD per 1M tokens: (input, output).
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
}

# For a model we don't recognise, assume the most expensive known rate. The cap
# exists to bound spend, so erring toward over-estimation fails safe: we might
# stop a hair early, but we never blow the budget by under-pricing.
_FALLBACK: tuple[float, float] = max(_PRICING.values(), key=lambda p: p[1])


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD cost of a run given cumulative input/output token counts."""
    in_rate, out_rate = _PRICING.get(model, _FALLBACK)
    return input_tokens / 1_000_000 * in_rate + output_tokens / 1_000_000 * out_rate
