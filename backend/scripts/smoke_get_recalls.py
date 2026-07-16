"""Smoke test: call the agent's get_recalls adapter against the LIVE NHTSA API
and print the trimmed output.

Proves the whole path end to end — agent adapter -> shared vehicle_safety_mcp
client -> live api.nhtsa.gov -> trimmed dict. Hits the network by design; not
part of the pytest suite.

Run:  uv run python backend/scripts/smoke_get_recalls.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Make the top-level `app` package importable when run as a script (backend/ is
# the source root, mirroring pyproject's pytest `pythonpath`).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.nhtsa import get_recalls  # noqa: E402


async def main() -> None:
    result = await get_recalls("Honda", "Civic", 2020)
    print(json.dumps(result, indent=2))

    count = result.get("count")
    returned = len(result.get("recalls", []))
    print(
        f"\n2020 Honda Civic: {count} recall campaign(s); "
        f"{returned} returned with details.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
