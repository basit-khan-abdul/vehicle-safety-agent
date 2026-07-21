"""Startup preflight: fail fast on a missing or invalid ANTHROPIC_API_KEY.

One cheap round-trip to the Messages API turns a misconfiguration into a single
clear message at startup, instead of the same failure repeating per question
deep in the loop (e.g. 25 identical errors across an eval run). Both entry
points — the eval harness and the FastAPI app — call this before doing any work.
"""

from __future__ import annotations

from app.core.config import Settings


class PreflightError(RuntimeError):
    """The Anthropic API key is missing or was rejected by a live check."""


def verify_anthropic_key(settings: Settings) -> None:
    """Confirm the key is present and accepted, with one minimal API call.

    Raises :class:`PreflightError` (single-line message) if the key is unset or
    the API rejects it. A successful call returns ``None``.
    """
    if not settings.anthropic_api_key:
        raise PreflightError(
            "ANTHROPIC_API_KEY is not set — add it to .env or the environment."
        )

    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        # max_tokens=1 keeps this to a few tokens: we only need the API to accept
        # the key. The response is discarded.
        client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except Exception as exc:
        raise PreflightError(
            f"ANTHROPIC_API_KEY was rejected by the Anthropic API "
            f"({type(exc).__name__}: {exc}). Check the key value and model "
            f"'{settings.anthropic_model}'."
        ) from exc
