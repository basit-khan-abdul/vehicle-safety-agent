"""rec_05 anti-hallucination regression (offline, mocked transport, runs in CI).

Milestone-4 lesson frozen as a guard. rec_05 (2018 Jeep Grand Cherokee) *looked*
like the agent padded a correct recall list with invented campaign numbers; live
reproduction showed it had not — but the failure mode is real and safety-critical,
so the *defense* must never silently regress. The defense is grounding: every
``\\d{2}[VE]\\d{6}`` recall token the agent emits must appear in a tool result from
that same turn (see ``run_evals._ungrounded_recall_numbers``); an ungrounded token
is a fabrication.

This drives the real ``run_agent`` loop with a scripted model + a mocked dispatch
that returns a KNOWN, closed set of recall numbers, then applies that grounding
check to the loop's own returned ``answer`` + ``tool_results``. Two directions,
both required:

  * a faithful answer citing exactly the tool's numbers has ZERO ungrounded tokens
    ("those and only those");
  * an answer that pads one extra number is CAUGHT — this proves the guard
    actually fires, so the first assertion cannot pass vacuously against a broken
    grounding check.

The grounding helper lives in ``evals/run_evals.py`` (not on the backend path), so
that directory is added to ``sys.path`` before importing it — the same seam
``test_eval_harness.py`` uses.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

from app.agent import loop as agent_loop
from app.agent.loop import run_agent
from app.core.config import Settings

EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"
sys.path.insert(0, str(EVALS_DIR))

from run_evals import _ungrounded_recall_numbers  # noqa: E402

# The known, closed set the mocked tool returns this turn — three real 2018 Jeep
# Grand Cherokee campaigns. Grounding must accept exactly these and reject anything
# the answer adds on top.
_KNOWN = ["18V280000", "18V332000", "20V699000"]
_JEEP_ARGS = {"make": "Jeep", "model": "Grand Cherokee", "model_year": 2018}
_QUESTION = "What recalls have been issued for the 2018 Jeep Grand Cherokee?"


# --- scripted Anthropic client (mirrors test_agent_loop.py) -------------------

def _usage(input_tokens=1000, output_tokens=200):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


def _tool_use(block_id, name, tool_input):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _response(content, stop_reason, usage=None):
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage or _usage())


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


def _known_recall_result():
    return {
        "count": len(_KNOWN),
        "recalls": [{"NHTSACampaignNumber": n, "Component": "TEST COMPONENT"} for n in _KNOWN],
    }


def _run_with_answer(monkeypatch, answer_text):
    """Run the real loop: turn 1 asks for get_recalls, turn 2 is ``answer_text``."""

    async def _fake_dispatch(name, arguments):
        assert name == "get_recalls"
        assert arguments == _JEEP_ARGS
        return _known_recall_result()

    monkeypatch.setattr(agent_loop.registry, "dispatch", _fake_dispatch)
    client = _ScriptedClient(
        [
            _response([_tool_use("t1", "get_recalls", _JEEP_ARGS)], "tool_use"),
            _response([_text(answer_text)], "end_turn", _usage(output_tokens=120)),
        ]
    )
    settings = Settings(anthropic_api_key="test")
    return run_agent(_QUESTION, settings=settings, client=client, logger=lambda *a, **k: None)


# --- the regression ----------------------------------------------------------

async def test_faithful_answer_has_those_and_only_those_numbers(monkeypatch):
    faithful = (
        "According to NHTSA [recalls:1], the 2018 Jeep Grand Cherokee has 3 recalls: "
        "18V280000 (park lock rod), 18V332000 (cruise control), and 20V699000."
    )
    result = await _run_with_answer(monkeypatch, faithful)

    # The loop captured the tool payload as grounding ground-truth.
    assert result["tool_results"] == [_known_recall_result()]

    # Contains those...
    for number in _KNOWN:
        assert number in result["answer"]
    # ...and ONLY those: no recall token in the answer is absent from this turn's
    # tool results. This is the rec_05 guard — a padded/invented number would show
    # up here.
    assert _ungrounded_recall_numbers(result["answer"], result["tool_results"]) == []


async def test_padded_invented_number_is_caught(monkeypatch):
    # The exact shape of the alleged rec_05 defect: correct numbers, then one more
    # that the tool never returned.
    padded = (
        "According to NHTSA [recalls:1], recalls include 18V280000, 18V332000, "
        "20V699000, and also 22V406000 (ABS module)."
    )
    result = await _run_with_answer(monkeypatch, padded)

    ungrounded = _ungrounded_recall_numbers(result["answer"], result["tool_results"])
    assert ungrounded == ["22V406000"], (
        "the grounding guard must flag a recall number that is not in the tool "
        "results — if this fails, the rec_05 defense has regressed"
    )
