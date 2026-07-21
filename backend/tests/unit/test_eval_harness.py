"""Harness-reliability units for the eval runner (offline, no network).

These lock in the three fixes that keep infrastructure and grader noise from
being scored as agent failures:
  * the judge retries transient outages and, on exhaustion, yields a THIRD
    outcome (`judge_error`) that is excluded from the pass-rate denominator;
  * an item whose tools returned `available: false` is tagged `infra_degraded`;
  * the report math and rendering honour both of the above.

The runner lives in ``evals/run_evals.py`` (not on the backend path), so we add
that directory to ``sys.path`` before importing it.
"""

import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"
sys.path.insert(0, str(EVALS_DIR))

import run_evals as R  # noqa: E402


class _HTTPish(Exception):
    """A stand-in transport error carrying an HTTP-style status code."""

    def __init__(self, status_code: int):
        super().__init__(f"boom {status_code}")
        self.status_code = status_code


class _FakeMessages:
    def __init__(self, exc: Exception):
        self._exc = exc
        self.calls = 0

    def create(self, **_kwargs):
        self.calls += 1
        raise self._exc


class _FakeClient:
    def __init__(self, exc: Exception):
        self.messages = _FakeMessages(exc)


# --- judge resilience --------------------------------------------------------

def test_judge_retries_transient_then_marks_judge_error(monkeypatch):
    monkeypatch.setattr(R, "_judge_sleep", lambda _s: None)  # no real backoff
    client = _FakeClient(_HTTPish(503))
    item = {"question": "q", "required_facts": [], "forbidden_behaviors": [], "grading_notes": ""}

    out = R.judge_check(item, "some answer", client)

    assert out["errored"] is True
    assert out["passed"] is None
    assert client.messages.calls == R._JUDGE_MAX_ATTEMPTS  # exhausted the retries
    assert f"after {R._JUDGE_MAX_ATTEMPTS} attempt" in out["error"]


def test_judge_fails_fast_on_non_retryable(monkeypatch):
    monkeypatch.setattr(R, "_judge_sleep", lambda _s: None)
    client = _FakeClient(_HTTPish(400))  # client error — won't fix itself
    item = {"question": "q", "required_facts": [], "forbidden_behaviors": [], "grading_notes": ""}

    out = R.judge_check(item, "some answer", client)

    assert out["errored"] is True
    assert client.messages.calls == 1  # no retries on a 4xx


def test_retryable_classifier():
    assert R._judge_retryable(_HTTPish(500)) is True
    assert R._judge_retryable(_HTTPish(503)) is True
    assert R._judge_retryable(_HTTPish(400)) is False
    assert R._judge_retryable(_HTTPish(429)) is False  # bare status; real RateLimitError is caught by type


# --- infra_degraded tagging --------------------------------------------------

def _stub_answer(monkeypatch, answer, tool_results):
    monkeypatch.setattr(
        R,
        "answer_fn",
        lambda _q: {"answer": answer, "citations": [], "tool_calls": [], "tool_results": tool_results},
    )


def test_infra_degraded_tag_set_when_tool_unavailable(monkeypatch):
    _stub_answer(monkeypatch, "NHTSA is unreachable right now.", [{"available": False, "source": "NHTSA"}])
    item = {"id": "x", "category": "us_recall_lookup", "question": "q", "required_facts": []}

    row = R.score_item(item, judge_client=None)  # no-judge path keeps it offline

    assert row["infra_degraded"] is True
    assert row["outcome"] in {"pass", "fail"}  # tagging is orthogonal to pass/fail


def test_infra_degraded_tag_absent_on_healthy_result(monkeypatch):
    _stub_answer(monkeypatch, "5 recalls incl 21V215000.", [{"count": 1, "recalls": []}])
    item = {"id": "x", "category": "us_recall_lookup", "question": "q", "required_facts": []}

    row = R.score_item(item, judge_client=None)

    assert row["infra_degraded"] is False


# --- report math -------------------------------------------------------------

def _row(rid, category, outcome, *, infra=False):
    return {
        "id": rid,
        "category": category,
        "question": f"q-{rid}",
        "answer": "a",
        "deterministic": {
            "status": "pass" if outcome == "pass" else "fail",
            "missing_facts": [],
            "forbidden_matched": [],
            "ungrounded_numbers": [],
            "facts_total": 0,
            "facts_found": 0,
        },
        "judge": (
            {"errored": True, "error": "judge call failed after 3 attempt(s): boom"}
            if outcome == "judge_error"
            else {"errored": False, "passed": outcome == "pass", "reasoning": "ok"}
        ),
        "passed": outcome == "pass",
        "outcome": outcome,
        "infra_degraded": infra,
    }


_META = {
    "date": "2026-07-21",
    "label": "t",
    "answer_source": "test",
    "judge_status": "claude-sonnet-4-6",
    "golden_version": "0.1.0",
    "golden_retrieved_on": "2026-07-17",
    "limit": None,
}


def test_judge_error_excluded_from_denominator():
    rows = [
        _row("a", "ambiguous", "pass"),
        _row("b", "ambiguous", "judge_error"),
        _row("c", "us_recall_lookup", "pass"),
    ]
    report = R.build_report(rows, _META)
    # 2 passes over a denominator of 2 (the judge_error is excluded), not 3.
    assert "## Overall: 2/2 passed (100%)" in report
    assert "(1 excluded: judge error)" in report
    assert "## Excluded — judge error (1)" in report


def test_infra_failures_summarised_but_still_counted():
    rows = [
        _row("a", "us_recall_lookup", "pass"),
        _row("b", "us_recall_lookup", "fail", infra=True),  # outage-driven refusal
    ]
    report = R.build_report(rows, _META)
    assert "## Overall: 1/2 passed (50%)" in report  # infra fail stays IN the denominator
    assert "upstream-unreachable" in report
    assert "infra: `degraded`" in report


def test_nhtsa_preflight_banner_rendered_when_down():
    meta = {**_META, "nhtsa_preflight": {"ok": False, "detail": "Could not connect to NHTSA."}}
    report = R.build_report([_row("a", "us_recall_lookup", "pass")], meta)
    assert "NHTSA was unreachable at the start of this run" in report
