"""Cost-cap abort path, proven with a mocked Anthropic client (no network, no key).

The loop must estimate spend from usage tokens and, once the cap is crossed,
abort BEFORE running any more tools or making another model call — returning a
truthful "budget exceeded" answer. Here the fake client reports a huge first-turn
usage while asking for a tool; with a tiny cap the loop must bail out before
dispatching that tool.
"""

from types import SimpleNamespace

import pytest

from app.agent import loop as agent_loop
from app.agent.loop import run_agent
from app.core.config import Settings


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _tool_use_response(input_tokens: int, output_tokens: int):
    """A response asking to call get_recalls, with the given (large) usage."""
    tool_use = SimpleNamespace(
        type="tool_use",
        id="toolu_1",
        name="get_recalls",
        input={"make": "Honda", "model": "Civic", "model_year": 2020},
    )
    return SimpleNamespace(
        content=[tool_use],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


async def test_loop_aborts_when_estimated_cost_exceeds_cap(monkeypatch):
    # Fail loudly if the loop ever dispatches a tool — it must not, because the
    # very first response already blows the budget.
    dispatched: list[str] = []

    async def _boom(name, arguments):
        dispatched.append(name)
        raise AssertionError("dispatch must not run once the budget is exceeded")

    monkeypatch.setattr(agent_loop.registry, "dispatch", _boom)

    # 1M input + 1M output on Sonnet 4.6 ≈ $3 + $15 = $18, far past the $0.01 cap.
    client = _FakeClient(_tool_use_response(1_000_000, 1_000_000))
    settings = Settings(
        anthropic_api_key="test",
        anthropic_model="claude-sonnet-4-6",
        max_cost_usd_per_run=0.01,
        max_tool_rounds=6,
    )

    result = await run_agent("Does the 2020 Honda Civic have any recalls?",
                             settings=settings, client=client, logger=lambda *a, **k: None)

    # Aborted before any tool ran.
    assert dispatched == []
    assert result["tool_calls"] == []
    assert result["citations"] == []
    # Exactly one model call was made (round 1), not another.
    assert len(client.messages.calls) == 1
    # Truthful budget-exceeded answer + accurate usage bookkeeping.
    assert result["usage"]["stop_reason"] == "budget_exceeded"
    assert "budget" in result["answer"].lower()
    assert result["usage"]["estimated_cost_usd"] >= settings.max_cost_usd_per_run
    assert result["usage"]["estimated_cost_usd"] == pytest.approx(18.0)


async def test_loop_returns_final_answer_without_hitting_cap(monkeypatch):
    """A cheap, direct answer (no tools) is returned normally, cap untouched."""

    async def _no_dispatch(name, arguments):
        raise AssertionError("no tool should be called for a direct answer")

    monkeypatch.setattr(agent_loop.registry, "dispatch", _no_dispatch)

    text_block = SimpleNamespace(type="text", text="Which model year of Civic do you mean?")
    response = SimpleNamespace(
        content=[text_block],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1200, output_tokens=40),
    )
    client = _FakeClient(response)
    settings = Settings(anthropic_api_key="test", anthropic_model="claude-sonnet-4-6")

    result = await run_agent("Is the Civic safe?", settings=settings, client=client,
                             logger=lambda *a, **k: None)

    assert result["answer"] == "Which model year of Civic do you mean?"
    assert result["citations"] == []
    assert result["usage"]["stop_reason"] == "end_turn"
    assert result["usage"]["estimated_cost_usd"] < settings.max_cost_usd_per_run
