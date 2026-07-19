"""Application settings.

Loaded from the environment (and a local ``.env`` when present) via
``pydantic-settings``. Field names map to UPPER_SNAKE env vars, so
``anthropic_api_key`` reads ``ANTHROPIC_API_KEY`` — matching ``.env.example``.

Every knob that governs cost or blast radius lives here so it is configurable
without code changes: the model, the tool-call ceiling, the output-token cap,
the hard per-request cost cap, and the per-IP rate limit.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env carries roadmap vars we don't read yet
    )

    # ---- Anthropic ----
    anthropic_api_key: str = ""
    # The agent runs on Sonnet 4.6 (also the eval judge model). Not Opus: the
    # investigation loop makes several calls per question, and Sonnet is the
    # cost/latency sweet spot for this tool-driven, well-scoped task.
    anthropic_model: str = "claude-sonnet-4-6"

    # Adaptive extended thinking: the model reasons before it plans tools and
    # before it writes the final brief — worth it for the safety-critical
    # citation/refusal discipline this agent is graded on. Off makes runs
    # cheaper and fully deterministic (used by the loop's unit tests).
    extended_thinking: bool = True

    # ---- Loop bounds ----
    max_tool_rounds: int = 6  # tool-call rounds before a forced final answer
    # Thinking tokens count toward the output budget, so leave headroom above
    # what the brief itself needs.
    max_output_tokens: int = 4096  # per Anthropic response

    # ---- Cost cap ----
    # Hard per-request ceiling. The loop estimates spend from usage tokens and
    # aborts before exceeding it, returning a truthful "budget exceeded" answer.
    max_cost_usd_per_run: float = 1.00

    # ---- Rate limit ----
    rate_limit: str = "10/minute"  # per client IP, enforced by slowapi


@lru_cache
def get_settings() -> Settings:
    """Process-wide singleton so env/.env is read once."""
    return Settings()
