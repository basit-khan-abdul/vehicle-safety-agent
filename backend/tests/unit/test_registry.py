"""Registry dispatch tests, run against a mocked HTTP transport.

We mock one layer *below* the client — at httpx's transport — so the real
``vehicle_safety_mcp`` client code executes (URL building, JSON parsing, field
trimming, and the composite VIN->recall chain) while no request ever leaves the
process. The seam is ``nhtsa._new_client``, which the client calls once per
request; we swap it for an ``AsyncClient`` wired to an ``httpx.MockTransport``.
"""

import json
from pathlib import Path

import httpx
import pytest

from vehicle_safety_mcp import nhtsa as client

from app.tools import registry

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    """Load a captured real NHTSA response (see fixtures/README rationale)."""
    return json.loads((_FIXTURES / name).read_text())


def _install_routes(monkeypatch, routes: dict[str, dict]) -> None:
    """Point the client's HTTP seam at a routed MockTransport.

    ``routes`` maps a substring of the request path to a JSON-able payload; the
    first matching route wins. An unmatched path raises, so a test can never
    quietly pass against an empty response it did not intend.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for needle, payload in routes.items():
            if needle in path:
                return httpx.Response(200, json=payload)
        raise AssertionError(f"unexpected request path: {path}")

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(client, "_new_client", factory)


async def test_dispatch_get_recalls_routes_and_trims(monkeypatch):
    _install_routes(
        monkeypatch,
        {
            "/recalls/recallsByVehicle": {
                "Count": 2,
                "results": [
                    {
                        "NHTSACampaignNumber": "21V215000",
                        "Component": "FUEL SYSTEM, GASOLINE",
                        "Summary": "s1",
                        "Consequence": "c1",
                        "Remedy": "r1",
                        "ReportReceivedDate": "2021-04-01",
                    },
                    {
                        "NHTSACampaignNumber": "23V458000",
                        "Component": "ELECTRICAL SYSTEM",
                        "Summary": "s2",
                        "Consequence": "c2",
                        "Remedy": "r2",
                        "ReportReceivedDate": "2023-07-01",
                    },
                ],
            }
        },
    )

    result = await registry.dispatch(
        "get_recalls", {"make": "Honda", "model": "Civic", "model_year": 2020}
    )

    assert result["count"] == 2
    assert [r["NHTSACampaignNumber"] for r in result["recalls"]] == [
        "21V215000",
        "23V458000",
    ]


async def test_dispatch_decode_vin_trims_real_noisy_vpic_payload(monkeypatch):
    # A real vPIC decode returns ~150 mostly-empty fields per vehicle. This
    # asserts the shared client trims that captured payload down to the
    # whitelisted signal fields — the trimming contract, exercised against the
    # actual upstream shape rather than a hand-built stand-in.
    raw = _load_fixture("vpic_decode_noisy.json")
    raw_record = raw["Results"][0]
    assert len(raw_record) > 100  # guard: the fixture really is the noisy shape
    assert "BatteryInfo" in raw_record  # a representative empty-noise field

    _install_routes(monkeypatch, {"/DecodeVinValues/": raw})

    result = await registry.dispatch(
        "decode_vin", {"vin": "5UXWX7C5*BA", "model_year": 2011}
    )

    # Right vehicle, and only whitelisted fields survive.
    assert result["Make"] == "BMW"
    assert result["Model"] == "X3"
    assert result["ModelYear"] == "2011"
    assert set(result).issubset(set(client._VIN_FIELDS))
    # Noise (and empty values) are gone.
    assert "BatteryInfo" not in result
    assert "Doors" not in result
    assert len(result) < len(raw_record)


async def test_dispatch_check_vin_recalls_chains_decode_then_recalls(monkeypatch):
    # The composite must hit vPIC to decode, then api.nhtsa.gov for recalls,
    # and stitch the two together. Distinct routes prove both legs ran.
    _install_routes(
        monkeypatch,
        {
            "/DecodeVinValues/": {
                "Results": [{"Make": "Honda", "Model": "Civic", "ModelYear": "2020"}]
            },
            "/recalls/recallsByVehicle": {
                "Count": 1,
                "results": [
                    {
                        "NHTSACampaignNumber": "21V215000",
                        "Component": "FUEL SYSTEM, GASOLINE",
                    }
                ],
            },
        },
    )

    result = await registry.dispatch("check_vin_recalls", {"vin": "2HGFC2F5XKH500000"})

    assert result["vehicle"]["Make"] == "Honda"
    assert result["count"] == 1
    assert result["recalls"][0]["NHTSACampaignNumber"] == "21V215000"


async def test_dispatch_get_complaints_uses_default_and_summarizes(monkeypatch):
    _install_routes(
        monkeypatch,
        {
            "/complaints/complaintsByVehicle": {
                "count": 3,
                "results": [
                    {"components": "ENGINE", "dateComplaintFiled": "2014-01-01"},
                    {"components": "ENGINE", "dateComplaintFiled": "2014-02-01"},
                    {"components": "STEERING", "dateComplaintFiled": "2014-03-01"},
                ],
            }
        },
    )

    # limit omitted -> adapter default (10) flows through to the client.
    result = await registry.dispatch(
        "get_complaints", {"make": "Ford", "model": "Escape", "model_year": 2013}
    )

    assert result["total_complaints"] == 3
    assert list(result["complaints_by_component"].items())[0] == ("ENGINE", 2)


async def test_dispatch_unknown_tool_raises_keyerror():
    with pytest.raises(KeyError):
        await registry.dispatch("de_orbit_the_moon", {})


def test_registry_is_aligned_and_unique():
    names = registry.tool_names()
    assert names == [
        "decode_vin",
        "check_vin_recalls",
        "get_recalls",
        "get_safety_ratings",
        "get_complaints",
    ]
    # The advertised schema array and the registered handlers stay in lockstep.
    assert [s["name"] for s in registry.TOOL_SCHEMAS] == names
    assert len(names) == len(set(names))
