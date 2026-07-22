"""EU Safety Gate client tests, run against a mocked HTTP transport (offline).

We mock at httpx's transport — the seam is ``eu_safety_gate._new_client`` — so the
real client code runs (request body, XML parsing, category filter, field
trimming, recency sort, and the degradation path) while no request leaves the
process. Ground-truth XML shapes mirror what the live ADR-002 probe returned.
"""

import httpx

from app.tools import eu_safety_gate as sg
from app.tools import registry

# A minimal Safety Gate export: two motor-vehicle notifications (one recent, one
# old) plus one non-vehicle notification that MUST be filtered out.
_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Safety-Gate>
  <notifications>
    <order>1</order>
    <caseNumber>A12/00188/24</caseNumber>
    <reference><![CDATA[https://ec.europa.eu/safety-gate-alerts/screen/webReport/alertDetail/-1]]></reference>
    <category><![CDATA[Motor vehicles]]></category>
    <product><![CDATA[Passenger car]]></product>
    <brand><![CDATA[VW - Volkswagen]]></brand>
    <type_numberOfModel><![CDATA[e1*2007/46*2180*]]></type_numberOfModel>
    <riskType><![CDATA[Fire]]></riskType>
    <danger><![CDATA[The thermal protection may fail.]]></danger>
    <description><![CDATA[Right-hand drive passenger car.]]></description>
    <measures><![CDATA[Recall of the product from end users]]></measures>
    <notifyingCountry><![CDATA[Germany]]></notifyingCountry>
    <countryOfOrigin><![CDATA[Germany]]></countryOfOrigin>
    <level><![CDATA[Serious risk]]></level>
    <batchNumber><![CDATA[]]></batchNumber>
  </notifications>
  <notifications>
    <order>2</order>
    <caseNumber>A12/00500/19</caseNumber>
    <category><![CDATA[Motor vehicles]]></category>
    <product><![CDATA[Passenger car]]></product>
    <brand><![CDATA[VW]]></brand>
    <riskType><![CDATA[Injuries]]></riskType>
    <notifyingCountry><![CDATA[Germany]]></notifyingCountry>
    <level><![CDATA[Serious risk]]></level>
  </notifications>
  <notifications>
    <order>3</order>
    <caseNumber>A12/09999/25</caseNumber>
    <category><![CDATA[Clothing, textiles and fashion items]]></category>
    <product><![CDATA[Jacket]]></product>
    <brand><![CDATA[VW Lifestyle]]></brand>
  </notifications>
</Safety-Gate>
"""


def _install(monkeypatch, *, response: httpx.Response | None = None, exc: Exception | None = None):
    """Route the client's HTTP seam to a MockTransport (or raise ``exc``)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if exc is not None:
            raise exc
        assert request.url.path.endswith("/download/search/xml/")
        return response

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(sg, "_new_client", factory)


async def test_parses_trims_and_filters_to_motor_vehicles(monkeypatch):
    _install(monkeypatch, response=httpx.Response(200, text=_XML))

    result = await registry.dispatch("search_eu_recalls", {"query": "Volkswagen"})

    # Non-vehicle (jacket) is dropped; only the two motor-vehicle alerts remain.
    assert result["count"] == 2
    assert result["source"] == "EU Safety Gate"
    assert result["jurisdiction"] == "EU"
    assert "partial" in result["coverage_note"].lower()

    # Recency sort: 2024 case before 2019 case.
    cases = [a["caseNumber"] for a in result["alerts"]]
    assert cases == ["A12/00188/24", "A12/00500/19"]

    # Trimming: signal kept, empty fields dropped.
    first = result["alerts"][0]
    assert first["brand"] == "VW - Volkswagen"
    assert first["riskType"] == "Fire"
    assert first["notifyingCountry"] == "Germany"
    assert "batchNumber" not in first  # empty -> dropped
    assert "order" not in first  # not a whitelisted field


async def test_max_results_caps_and_clamps(monkeypatch):
    _install(monkeypatch, response=httpx.Response(200, text=_XML))

    result = await registry.dispatch(
        "search_eu_recalls", {"query": "Volkswagen", "max_results": 1}
    )
    assert result["count"] == 1
    assert result["alerts"][0]["caseNumber"] == "A12/00188/24"  # most recent kept


async def test_request_body_shape(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, text=_XML)

    monkeypatch.setattr(
        sg, "_new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    await sg.search_eu_recalls("Tesla Model 3", max_results=5)
    body = captured["body"]
    assert body["fullTextSearch"] == "Tesla Model 3"
    assert body["language"] == "en"
    assert "pagination" in body and "criteria" in body


async def test_5xx_degrades_honestly_after_retries(monkeypatch):
    monkeypatch.setattr(sg, "_sleep", _noop_sleep)  # neutralise backoff
    _install(monkeypatch, response=httpx.Response(503, text="upstream down"))

    result = await registry.dispatch("search_eu_recalls", {"query": "BMW"})

    assert result["available"] is False
    assert result["source"] == "EU Safety Gate"
    assert result["jurisdiction"] == "EU"
    assert "unreachable" in result["error"].lower()
    assert "count" not in result  # a degradation payload, not a result set


async def test_connection_error_degrades(monkeypatch):
    monkeypatch.setattr(sg, "_sleep", _noop_sleep)
    _install(monkeypatch, exc=httpx.ConnectError("no route to host"))

    result = await sg.search_eu_recalls("Volkswagen")
    assert result["available"] is False
    assert "EU Safety Gate" in result["source"]


async def test_4xx_fails_fast_without_retry(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    monkeypatch.setattr(
        sg, "_new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    result = await sg.search_eu_recalls("BMW")
    assert result["available"] is False
    assert calls["n"] == 1  # 4xx is not retried


async def _noop_sleep(_seconds):
    return None
