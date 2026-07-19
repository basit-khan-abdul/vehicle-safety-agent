"""Live smoke tests against the real NHTSA APIs, through the agent's adapters.

These hit the network on purpose. Unlike the package's own live suite (which
exercises the shared client directly), these go through ``app.tools.nhtsa`` —
the agent's import surface — so they prove the *agent's* integration path still
lines up with the live NHTSA contract: adapter -> shared vehicle_safety_mcp
client -> live api.nhtsa.gov / vpic -> trimmed dict.

They are marked ``live`` and excluded from the default push/PR CI (see the
``addopts = -m 'not live'`` in pyproject). The weekly
``.github/workflows/contract-drift.yml`` job runs them and opens an issue if the
upstream contract drifts. No API key is required — the NHTSA APIs are public.

Run explicitly:  uv run --no-sync pytest -m live
"""

import pytest

from app.tools import nhtsa

pytestmark = pytest.mark.live


async def test_decode_vin_live():
    result = await nhtsa.decode_vin("5UXWX7C5*BA", model_year=2011)
    assert result["Make"] == "BMW"
    assert result["Model"] == "X3"
    assert result["ModelYear"] == "2011"


async def test_get_recalls_live():
    result = await nhtsa.get_recalls("Honda", "Civic", 2020)
    # Count is a floor that only grows; the 2020 Civic has multiple campaigns.
    assert result["count"] >= 1
    first = result["recalls"][0]
    assert "NHTSACampaignNumber" in first
    assert "Component" in first


async def test_get_safety_ratings_live():
    result = await nhtsa.get_safety_ratings("Honda", "Civic", 2020)
    assert result["variant_count"] >= 1
    assert any("OverallRating" in r for r in result["ratings"])


async def test_get_complaints_live():
    result = await nhtsa.get_complaints("Honda", "Civic", 2020, limit=3)
    assert result["total_complaints"] >= 1
    assert len(result["recent_complaints"]) <= 3
    assert result["complaints_by_component"]
