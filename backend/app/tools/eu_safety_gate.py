"""EU Safety Gate recall client (ADR 002).

Safety Gate (formerly RAPEX) is the EU rapid-alert system for dangerous non-food
products. It carries a live, keyless, **undocumented** API behind a WAF — the
internal API of the public Angular site, not a published contract. Per ADR 002
we consume its **XML search export** (`POST …/api/download/search/xml/`), which
was the one surface that answered server-to-server during the scope probe (the
JSON `search`/`getSearchCriteria` endpoints return 405/WAF to non-browser
clients). We filter the result to the **Motor vehicles** category and trim to the
fields that change a safety answer.

This module deliberately mirrors the NHTSA client's *contract* — explicit
timeouts, bounded retry with jittered backoff, and a structured
``{"available": false, …}`` degradation payload the agent relays honestly rather
than papering over — because ADR 002 chose consistency with how the project
already handles an unreliable upstream. It does not share code with that client:
the endpoint, request body, and XML shape are entirely different, and the NHTSA
client lives in the published ``vehicle-safety-mcp`` package.

Honesty constraints baked in (ADR 002 §Decision):
- Results are labelled ``jurisdiction: "EU"`` / ``source: "EU Safety Gate"`` and
  must never be blended into a US answer without that label.
- Safety Gate is notification-driven, Germany-heavy, and keyed by **type-approval
  number**, not consumer year/make/model — so coverage is **partial** and a match
  is by brand/free-text, not an exact model lookup. ``coverage_note`` says so on
  every successful response, and an empty result is reported as "none found in
  Safety Gate", never as "this vehicle has no EU recalls".
"""

from __future__ import annotations

import asyncio
import functools
import os
import random
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

# The XML search export. Base host + path read from the SPA bundle during the
# ADR-002 probe; the trailing slash is required (without it the endpoint 405s).
_BASE = "https://ec.europa.eu/safety-gate-alerts"
_SEARCH_XML_URL = f"{_BASE}/api/download/search/xml/"

# Browser-like headers: the WAF (Dynatrace, owasp=1) serves an HTML interstitial
# to naive clients but returns clean data when these are present (ADR 002).
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": f"{_BASE}/",
    "Accept": "application/xml, text/xml, */*",
    "Content-Type": "application/json",
    "lang": "en",
}

# The Safety Gate product category we care about. The export tags every record
# with a <category>; motor-vehicle recalls carry exactly this label.
_MOTOR_VEHICLES = "Motor vehicles"

# Timeouts (env-tunable). The export is heavy — a broad query can stream a large
# document slowly — so the read timeout is generous but bounded; a truly broad
# query that overruns it degrades honestly rather than hanging the agent.
_CONNECT_TIMEOUT = float(os.getenv("EU_SG_CONNECT_TIMEOUT", "10.0"))
_READ_TIMEOUT = float(os.getenv("EU_SG_READ_TIMEOUT", "30.0"))

# Retry policy (env-tunable) — same shape as the NHTSA client: bounded attempts,
# exponential base, and a cap so jittered growth stays bounded.
_MAX_ATTEMPTS = int(os.getenv("EU_SG_MAX_ATTEMPTS", "3"))
_BACKOFF_BASE = float(os.getenv("EU_SG_BACKOFF_BASE", "0.5"))
_BACKOFF_CAP = float(os.getenv("EU_SG_BACKOFF_CAP", "8.0"))

# Default cap on alerts returned to the agent. The export returns a vehicle's
# whole history (hundreds of rows for a big marque); we keep the most recent N.
_DEFAULT_MAX_RESULTS = 10

# Fields worth surfacing from a motor-vehicle notification (of ~22 in the DTO).
# `caseNumber` is the stable Safety Gate reference (the EU analogue of an NHTSA
# campaign number); the rest is what changes a safety answer.
_ALERT_FIELDS = [
    "caseNumber",
    "brand",
    "product",
    "type_numberOfModel",
    "riskType",
    "danger",
    "description",
    "measures",
    "notifyingCountry",
    "countryOfOrigin",
    "level",
    "reference",
]

_COVERAGE_NOTE = (
    "EU Safety Gate (RAPEX) motor-vehicle coverage is partial and notification-driven "
    "(heavily Germany-sourced) and is keyed by brand and type-approval number, not by "
    "consumer model year. Matches are by brand/free-text search, not an exact "
    "make/model/year lookup; an empty result means nothing was found in Safety Gate, "
    "not that the vehicle is recall-free. For authoritative national data see the "
    "official Safety Gate portal and national authorities (e.g. KBA in Germany)."
)


class SafetyGateUnavailable(RuntimeError):
    """Safety Gate could not be reached (after retries) or refused the request."""


async def _sleep(seconds: float) -> None:
    """Backoff sleep. Indirected so tests can neutralise the wait."""
    await asyncio.sleep(seconds)


def _new_client() -> httpx.AsyncClient:
    """Build the HTTP client. Isolated so tests can inject a mock transport."""
    timeout = httpx.Timeout(
        connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=_READ_TIMEOUT, pool=_CONNECT_TIMEOUT
    )
    return httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_HEADERS)


def _is_retryable(exc: Exception) -> bool:
    """Retry only transient failures: 5xx responses and transport errors
    (connection failures + timeouts). Never retry 4xx — a client error won't
    fix itself."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


def _describe(exc: Exception) -> str:
    """A short, honest reason string for the degradation payload."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code >= 500:
            return f"EU Safety Gate returned a server error (HTTP {code})."
        return f"EU Safety Gate rejected the request (HTTP {code})."
    if isinstance(exc, httpx.TimeoutException):
        return "The request to EU Safety Gate timed out."
    if isinstance(exc, ET.ParseError):
        return "EU Safety Gate returned a response that could not be parsed as XML."
    return "Could not connect to EU Safety Gate."


def _search_body(query: str, max_results: int) -> dict[str, Any]:
    """The reverse-engineered search-export request body (ADR 002 probe).

    The server binds this to its search DTO; `criteria` stays empty (we filter to
    motor vehicles client-side, since the category-enum token is not published),
    and `fullTextSearch` carries the make/model. Unknown pagination keys are
    ignored by the server, so we also cap client-side.
    """
    return {
        "fullTextSearch": query,
        "pagination": {
            "itemsPerPage": max_results,
            "page": 0,
            "sortBy": "SORT_BY_PUBLICATION_DATE",
            "sortOrder": "DESC",
        },
        "criteria": {},
        "language": "en",
        "displayDefaultResults": False,
        "isForMostRecent": False,
    }


async def _post_xml(body: dict[str, Any]) -> str:
    """POST the search body and return the XML text, or raise SafetyGateUnavailable.

    Retries transient failures (5xx, connection errors, timeouts) up to
    ``_MAX_ATTEMPTS`` with exponential backoff + full jitter; 4xx fails fast.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            async with _new_client() as client:
                resp = await client.post(_SEARCH_XML_URL, json=body)
                resp.raise_for_status()
                return resp.text
        except Exception as exc:  # noqa: BLE001 — re-raised as SafetyGateUnavailable
            last_exc = exc
            if not _is_retryable(exc) or attempt == _MAX_ATTEMPTS:
                break
            ceiling = min(_BACKOFF_CAP, _BACKOFF_BASE * 2 ** (attempt - 1))
            await _sleep(random.uniform(0, ceiling))

    assert last_exc is not None
    raise SafetyGateUnavailable(_describe(last_exc)) from last_exc


def _text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def _case_year(case_number: str) -> int:
    """Sort key: the two-digit year trailing a Safety Gate case number
    (``A12/00188/24`` -> 24, ``1106/10`` -> 10). Unknown -> -1 (sorts last)."""
    tail = case_number.rsplit("/", 1)[-1] if "/" in case_number else ""
    return int(tail) if tail.isdigit() and len(tail) == 2 else -1


def _trim_alert(node: ET.Element) -> dict[str, Any]:
    """Keep the answer-changing fields of one notification, dropping empties."""
    out: dict[str, Any] = {}
    for tag in _ALERT_FIELDS:
        val = _text(node, tag)
        if val:
            out[tag] = val
    return out


def _parse_motor_vehicle_alerts(xml_text: str, max_results: int) -> list[dict[str, Any]]:
    """Parse the export, keep only Motor-vehicle notifications, most-recent first."""
    root = ET.fromstring(xml_text)
    motor = [
        node
        for node in root.findall(".//notifications")
        if _text(node, "category") == _MOTOR_VEHICLES
    ]
    motor.sort(key=lambda n: _case_year(_text(n, "caseNumber")), reverse=True)
    return [_trim_alert(n) for n in motor[:max_results]]


def _graceful(
    fn: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Turn a ``SafetyGateUnavailable`` into a structured payload instead of a
    traceback, so tool callers never see a raw crash."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return await fn(*args, **kwargs)
        except SafetyGateUnavailable as exc:
            return _unavailable(str(exc))

    return wrapper


def _unavailable(detail: str) -> dict[str, Any]:
    """Structured degradation payload — mirrors the NHTSA client's shape so the
    agent relays an EU outage exactly as it relays a US one."""
    return {
        "error": "EU Safety Gate recall data is currently unreachable; please try again later.",
        "detail": detail,
        "source": "EU Safety Gate",
        "jurisdiction": "EU",
        "available": False,
    }


@_graceful
async def search_eu_recalls(query: str, max_results: int = _DEFAULT_MAX_RESULTS) -> dict[str, Any]:
    """Search EU Safety Gate for motor-vehicle recall alerts matching ``query``.

    ``query`` is free text (make and/or model, e.g. "Volkswagen" or "Tesla Model
    3"); Safety Gate matches it across its alert text. Returns the most-recent
    motor-vehicle alerts with their Safety Gate case numbers and details, plus a
    coverage caveat. Never raises — an unreachable upstream returns the
    ``available: false`` degradation payload.
    """
    max_results = max(1, min(int(max_results), 50))
    xml_text = await _post_xml(_search_body(query, max_results))
    alerts = _parse_motor_vehicle_alerts(xml_text, max_results)
    return {
        "query": query,
        "count": len(alerts),
        "alerts": alerts,
        "source": "EU Safety Gate",
        "jurisdiction": "EU",
        "coverage_note": _COVERAGE_NOTE,
    }
