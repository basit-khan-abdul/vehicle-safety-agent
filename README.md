# vehicle-safety-agent

[![CI](https://github.com/basit-khan-abdul/vehicle-safety-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/basit-khan-abdul/vehicle-safety-agent/actions/workflows/ci.yml)

## What this is

vehicle-safety-agent is an agentic system that investigates vehicle-safety questions
end to end. Claude (via the Anthropic API) plans and runs a tool-driven investigation —
starting with US **NHTSA** data through the published
[`vehicle-safety-mcp`](https://github.com/basit-khan-abdul/vehicle-safety-mcp) package
(VIN decoding, recalls, NCAP crash-test ratings, complaints) — and produces a **cited
safety brief** where every claim traces back to the source record it came from.

The project is **evals-first**: before the agent does anything useful, a graded eval set
defines what a good safety brief looks like — coverage, factual grounding, and citation
accuracy — so changes are measured, not guessed at. Later phases extend coverage to the
EU market (RAPEX / KBA recall data and US ↔ EU cross-referencing) and add
retrieval-augmented generation over Euro NCAP test protocols. A TypeScript frontend and a
public deployment come after the core is trustworthy.

## Architecture

> Diagram placeholder. See [ARCHITECTURE.md](ARCHITECTURE.md) for the written breakdown
> (Problem / Constraints / Components / Data flow / Key decisions).

<!-- TODO: architecture diagram — agent loop, tools, data sources, cited-brief output. -->

## Eval results

Populated from [`evals/results/`](evals/results/). **No numbers until there are numbers** —
this table stays empty until a real eval run produces them.

| date | eval set version | pass rate | citation accuracy | notes |
|------|------------------|-----------|-------------------|-------|
| —    | —                | —         | —                 | —     |

## Status

**First slice working, live baseline not yet run.** The scaffold, CI, and docs skeleton
are in place. The golden eval set (25 graded questions across 7 categories) and its
grading harness are committed. The tool layer is wired to
[`vehicle-safety-mcp`](https://github.com/basit-khan-abdul/vehicle-safety-mcp) v0.2.0
(VIN decode, recalls, NCAP ratings, complaints), reusing its resilient HTTP client
(timeouts, bounded retry, honest degradation) as-is. The agent slice is implemented: a
Claude tool-use loop with adaptive extended thinking that turns a question into a cited
brief, served over `POST /ask` with per-request cost and per-IP rate caps. Tests are
split into offline unit (mocked transport, Python 3.11 + 3.12 in CI) and live NHTSA
suites, with a weekly contract-drift job. The live eval baseline **has not been run yet**
— it needs an `ANTHROPIC_API_KEY`, so the only committed result is the stub run (0%) and
the Eval results table above stays empty until a real run produces numbers.

## Testing philosophy

Tests split into two suites by what they trust. **Unit** tests (`backend/tests/unit/`)
mock at httpx's transport, so the real shared client and its field-trimming execute
offline and deterministically on every push and PR (Python 3.11 + 3.12) — no network,
no flakiness, no API key. **Live** tests (`backend/tests/live/`, marked `live` and
excluded by default; run with `pytest -m live`) hit the real NHTSA APIs to validate the
actual upstream contract, and run only on demand or via a weekly scheduled job. When that
weekly [contract-drift job](.github/workflows/contract-drift.yml) fails it auto-opens an
issue, so an upstream change (a moved endpoint, a renamed field, a shifted response shape)
surfaces as tracked breakage instead of silently wrong safety briefs.

## Roadmap

1. **US recall slice** — agent investigates NHTSA recalls / ratings / complaints via
   `vehicle-safety-mcp` and produces a cited brief, graded against the eval set.
2. **EU cross-reference** — add RAPEX / KBA recall data and cross-reference US ↔ EU.
3. **RAG over NCAP docs** — retrieval-augmented answers grounded in Euro NCAP protocols.
4. **TypeScript frontend** — a UI over the agent (see [`frontend/`](frontend/)).
5. **Public deployment** — hosted, rate- and cost-capped, publicly reachable.

## License

MIT — see [LICENSE](LICENSE).
