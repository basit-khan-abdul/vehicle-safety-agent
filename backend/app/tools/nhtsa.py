"""Thin async adapters over the shared NHTSA client.

Each function here wraps the corresponding call in `vehicle_safety_mcp`'s NHTSA
client and returns the client's already-trimmed dict unchanged. The adapters
add no data shaping of their own, on purpose: the trimming and the resilient
HTTP behaviour (timeouts, retries, and the structured ``{"available": False}``
degradation payload emitted when NHTSA is unreachable) live in one place — the
package — shared byte-for-byte with the MCP server. Duplicating any of it here
would be the one failure mode this layer exists to avoid.

Why a wrapper module at all, if it only delegates: it gives the agent one
stable, import-friendly surface (`app.tools.nhtsa`) that the registry binds to
Anthropic tool schemas, and a single seam to add cross-cutting concerns later
(per-call logging, cost accounting, caching) without touching the package.

`check_vin_recalls` is the lone composite — it chains decode → resolve →
recall-lookup with real edge-case handling. That composition lives in the
package's server module; we import and delegate to it rather than re-implement
the chaining here.
"""

from __future__ import annotations

from typing import Any

from vehicle_safety_mcp import nhtsa as _client
from vehicle_safety_mcp.server import check_vin_recalls as _check_vin_recalls


async def decode_vin(vin: str, model_year: int | None = None) -> dict[str, Any]:
    """Decode a full or partial VIN into vehicle attributes."""
    return await _client.decode_vin(vin, model_year)


async def check_vin_recalls(vin: str) -> dict[str, Any]:
    """Decode a VIN and return recalls for that exact vehicle, in one step."""
    return await _check_vin_recalls(vin)


async def get_recalls(make: str, model: str, model_year: int) -> dict[str, Any]:
    """Fetch NHTSA recall campaigns for a make/model/year."""
    return await _client.get_recalls(make, model, model_year)


async def get_safety_ratings(make: str, model: str, model_year: int) -> dict[str, Any]:
    """Fetch NCAP crash-test ratings for a make/model/year."""
    return await _client.get_safety_ratings(make, model, model_year)


async def get_complaints(
    make: str, model: str, model_year: int, limit: int = 10
) -> dict[str, Any]:
    """Fetch consumer complaints for a make/model/year, summarized by component."""
    return await _client.get_complaints(make, model, model_year, limit)
