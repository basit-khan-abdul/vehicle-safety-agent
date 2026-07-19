"""End-to-end loop behaviour, driven by a scripted mock Anthropic client.

These exercise the real investigation loop — tool dispatch, feeding results back
tagged with citation markers, marker→citation reconciliation, the forced final
answer after the round budget, and the extended-thinking toggle — entirely
offline. This is the same path the live ``/ask`` acceptance runs, minus the real
model, so it can be verified without an API key.
"""

from types import SimpleNamespace

from app.agent import loop as agent_loop
from app.agent.loop import run_agent
from app.core.config import Settings

_CIVIC_ARGS = {"make": "Honda", "model": "Civic", "model_year": 2020}


def _usage(input_tokens=1000, output_tokens=200):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


def _thinking():
    return SimpleNamespace(type="thinking", thinking="Plan: look up the recalls.")


def _tool_use(block_id, name, tool_input):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _response(content, stop_reason, usage=None):
    return SimpleNamespace(
        content=content, stop_reason=stop_reason, usage=usage or _usage()
    )


class _ScriptedMessages:
    """Returns queued responses in order, recording every create() call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _ScriptedClient:
    def __init__(self, responses):
        self.messages = _ScriptedMessages(responses)


def _has_tool_result(messages) -> bool:
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    return True
    return False


async def test_multi_round_tool_use_then_cited_answer(monkeypatch):
    async def _fake_dispatch(name, arguments):
        assert name == "get_recalls"
        assert arguments == _CIVIC_ARGS
        return {
            "count": 5,
            "recalls": [
                {"NHTSACampaignNumber": "21V215000", "Component": "FUEL SYSTEM"},
                {"NHTSACampaignNumber": "23V458000", "Component": "SERVICE BRAKES"},
            ],
        }

    monkeypatch.setattr(agent_loop.registry, "dispatch", _fake_dispatch)

    client = _ScriptedClient(
        [
            _response(
                [_thinking(), _tool_use("t1", "get_recalls", _CIVIC_ARGS)],
                "tool_use",
            ),
            _response(
                [
                    _text(
                        "Per NHTSA, the 2020 Honda Civic has 5 recall campaigns "
                        "[recalls:1], including 21V215000 and 23V458000."
                    )
                ],
                "end_turn",
                _usage(output_tokens=120),
            ),
        ]
    )
    settings = Settings(anthropic_api_key="test")  # defaults: thinking on

    result = await run_agent(
        "Does the 2020 Honda Civic have any recalls?",
        settings=settings,
        client=client,
        logger=lambda *a, **k: None,
    )

    # A cited answer carrying the ground-truth campaign number.
    assert "21V215000" in result["answer"]
    assert result["citations"] == [
        {
            "marker": "recalls:1",
            "tool": "get_recalls",
            "args": _CIVIC_ARGS,
            "excerpt": result["citations"][0]["excerpt"],
        }
    ]
    assert "21V215000" in result["citations"][0]["excerpt"]

    # Audit trail of what ran.
    assert result["tool_calls"] == [
        {"marker": "recalls:1", "tool": "get_recalls", "args": _CIVIC_ARGS, "available": True}
    ]
    assert result["usage"]["rounds"] == 2
    assert result["usage"]["stop_reason"] == "end_turn"

    # The tool result was fed back into the second model call...
    assert _has_tool_result(client.messages.calls[1]["messages"])
    # ...and extended thinking was requested on each call.
    assert client.messages.calls[0]["thinking"] == {"type": "adaptive"}


async def test_forced_final_answer_after_max_rounds(monkeypatch):
    async def _fake_dispatch(name, arguments):
        return {"count": 0, "recalls": []}

    monkeypatch.setattr(agent_loop.registry, "dispatch", _fake_dispatch)

    # The model never stops asking for tools, so the loop must force a final
    # answer once the round budget is spent.
    tool_rounds = [
        _response([_tool_use(f"t{i}", "get_recalls", _CIVIC_ARGS)], "tool_use")
        for i in range(6)
    ]
    forced_final = _response([_text("Final answer, no more tools.")], "end_turn")
    client = _ScriptedClient(tool_rounds + [forced_final])
    settings = Settings(anthropic_api_key="test", max_tool_rounds=6)

    result = await run_agent("q", settings=settings, client=client, logger=lambda *a, **k: None)

    assert result["answer"] == "Final answer, no more tools."
    # 6 tool rounds + 1 forced final = 7 model calls.
    assert len(client.messages.calls) == 7
    assert result["usage"]["rounds"] == 7
    # The forced-final call withholds tools so the model must answer.
    assert "tools" not in client.messages.calls[6]


async def test_thinking_disabled_omits_kwarg(monkeypatch):
    async def _no_dispatch(name, arguments):
        raise AssertionError("no tool should run for a direct answer")

    monkeypatch.setattr(agent_loop.registry, "dispatch", _no_dispatch)

    client = _ScriptedClient([_response([_text("hello")], "end_turn")])
    settings = Settings(anthropic_api_key="test", extended_thinking=False)

    await run_agent("q", settings=settings, client=client, logger=lambda *a, **k: None)

    assert "thinking" not in client.messages.calls[0]
