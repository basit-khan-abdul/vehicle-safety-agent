"""Live smoke tests against the real EU Safety Gate export (ADR 002).

These hit the network on purpose, through the agent's import surface
(``app.tools.eu_safety_gate``), to prove the agent's integration path still
matches the live, undocumented Safety Gate XML export: browser-headered POST ->
XML -> motor-vehicle filter -> trimmed dict.

Marked ``live`` and excluded from default push/PR CI (``addopts = -m 'not
live'``); the weekly contract-drift job runs them so an upstream shape change on
this WAF-fronted, unofficial API surfaces as tracked breakage rather than a
silently empty EU answer. No API key required — Safety Gate is public.

Because Safety Gate sits behind a WAF that intermittently degrades
server-to-server calls, each assertion tolerates one honest degradation and
retries a few times before failing — the point is to catch a *contract* change,
not a transient outage.

Run explicitly:  uv run --no-sync pytest -m live
"""

import asyncio

import pytest

from app.tools import eu_safety_gate as sg

pytestmark = pytest.mark.live


async def _search_with_retry(query: str, *, max_results: int = 5, attempts: int = 4) -> dict:
    """Return the first non-degraded result, or the last degradation payload."""
    result: dict = {}
    for _ in range(attempts):
        result = await sg.search_eu_recalls(query, max_results=max_results)
        if result.get("available") is not False:
            return result
        await asyncio.sleep(3)
    return result


async def test_search_eu_recalls_live_motor_vehicles():
    result = await _search_with_retry("Volkswagen")
    if result.get("available") is False:
        pytest.skip(f"Safety Gate degraded across retries: {result.get('detail')}")

    assert result["source"] == "EU Safety Gate"
    assert result["jurisdiction"] == "EU"
    assert result["count"] >= 1
    first = result["alerts"][0]
    # The stable Safety Gate reference (EU analogue of an NHTSA campaign number).
    assert first.get("caseNumber")
    assert "/" in first["caseNumber"]
    # Contract: every returned alert is a trimmed motor-vehicle record.
    assert "brand" in first
    assert set(first).issubset(set(sg._ALERT_FIELDS))


async def test_search_eu_recalls_live_cross_reference_brand():
    result = await _search_with_retry("Tesla Model 3")
    if result.get("available") is False:
        pytest.skip(f"Safety Gate degraded across retries: {result.get('detail')}")
    assert result["count"] >= 1
    assert all(a.get("caseNumber") for a in result["alerts"])
