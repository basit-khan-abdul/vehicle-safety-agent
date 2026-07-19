"""The agent must relay an NHTSA outage honestly, never mask or fabricate.

When the shared client can't reach NHTSA it returns a structured degradation
payload (``{"available": False, "error", "detail", "source"}``) instead of
raising. This test drives the real loop with a mocked model + a dispatch that
returns that payload, and asserts the agent surfaces the outage: the tool audit
marks the call unavailable, the outage text is fed back to the model, and a
citation to it carries the honest error string rather than invented data.

The client's own resilience (timeouts/retry/degradation) is unit-tested in the
vehicle_safety_mcp package; this asserts the *agent's* handling of that payload.
"""

from types import SimpleNamespace

from app.agent import loop as agent_loop
from app.agent.loop import run_agent
from app.core.config import Settings

# Exactly the shape vehicle_safety_mcp emits when NHTSA is unreachable.
_DEGRADED = {
    "error": "NHTSA vehicle-safety data is currently unreachable; please try again later.",
    "detail": "The request to NHTSA timed out.",
    "source": "NHTSA",
    "available": False,
}
_ARGS = {"make": "Honda", "model": "Civic", "model_year": 2020}


def _usage(input_tokens=1000, output_tokens=120):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


def _tool_use(block_id, name, tool_input):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _response(content, stop_reason):
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=_usage())


class _ScriptedMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _ScriptedClient:
    def __init__(self, responses):
        self.messages = _ScriptedMessages(responses)


def _tool_result_text(messages) -> str:
    """Concatenate every tool_result payload fed back to the model."""
    chunks: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    chunks.append(str(block.get("content", "")))
    return "\n".join(chunks)


async def test_agent_relays_nhtsa_outage_honestly(monkeypatch):
    async def _fake_dispatch(name, arguments):
        assert name == "get_recalls"
        return _DEGRADED

    monkeypatch.setattr(agent_loop.registry, "dispatch", _fake_dispatch)

    client = _ScriptedClient(
        [
            _response([_tool_use("t1", "get_recalls", _ARGS)], "tool_use"),
            _response(
                [
                    _text(
                        "I can't confirm recalls right now: NHTSA's data is "
                        "currently unreachable [recalls:1]. Please try again "
                        "shortly or check nhtsa.gov directly."
                    )
                ],
                "end_turn",
            ),
        ]
    )
    settings = Settings(anthropic_api_key="test", extended_thinking=False)

    result = await run_agent(
        "Does the 2020 Honda Civic have any recalls?",
        settings=settings,
        client=client,
        logger=lambda *a, **k: None,
    )

    # The audit trail marks the call as unavailable — the outage isn't hidden.
    assert result["tool_calls"] == [
        {"marker": "recalls:1", "tool": "get_recalls", "args": _ARGS, "available": False}
    ]

    # The degradation payload was actually fed back to the model (available:false
    # + the honest reason), so the model answered from the outage, not a guess.
    fed_back = _tool_result_text(client.messages.calls[1]["messages"])
    assert '"available": false' in fed_back
    assert "unreachable" in fed_back

    # A citation to the outage carries the honest error text, not fabricated data.
    assert len(result["citations"]) == 1
    citation = result["citations"][0]
    assert citation["marker"] == "recalls:1"
    assert "unreachable" in citation["excerpt"].lower()
    # No invented campaign numbers leak into the excerpt.
    assert "21V" not in citation["excerpt"]
