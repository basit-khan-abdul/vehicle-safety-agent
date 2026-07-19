# Captured NHTSA fixtures

Real responses snapshotted from the live NHTSA APIs, used by the **unit** suite
to exercise the shared `vehicle_safety_mcp` client's trimming/parsing against the
*actual* upstream shape — offline and deterministically — instead of hand-built
stand-ins that can quietly drift from reality.

| file | endpoint | why |
|------|----------|-----|
| `vpic_decode_noisy.json` | vPIC `DecodeVinValues` (2011 BMW X3) | The full ~150-field payload; proves trimming keeps only the whitelisted signal fields. |
| `recalls_civic_2020.json` | `recalls/recallsByVehicle` (2020 Honda Civic) | Raw recall record shape (first 3 campaigns). |
| `complaints_civic_2020.json` | `complaints/complaintsByVehicle` (2020 Honda Civic) | Raw complaint record shape (first 3, narratives truncated). |

These are static test data, not a live contract — the **live** suite
(`backend/tests/live/`, `-m live`) and the weekly contract-drift workflow are what
catch upstream drift. Refresh a fixture only intentionally, when the client's
parsing is deliberately updated.
