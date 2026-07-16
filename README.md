# vehicle-safety-agent

<!-- Badges intentionally omitted until CI has run and there is a release to point at. -->

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

**Day 1 — scaffold only. Nothing works yet.** The directory layout, CI, and documentation
skeletons exist. There is no agent logic, no tools wired up, and no eval set written yet.

## Roadmap

1. **US recall slice** — agent investigates NHTSA recalls / ratings / complaints via
   `vehicle-safety-mcp` and produces a cited brief, graded against the eval set.
2. **EU cross-reference** — add RAPEX / KBA recall data and cross-reference US ↔ EU.
3. **RAG over NCAP docs** — retrieval-augmented answers grounded in Euro NCAP protocols.
4. **TypeScript frontend** — a UI over the agent (see [`frontend/`](frontend/)).
5. **Public deployment** — hosted, rate- and cost-capped, publicly reachable.

## License

MIT — see [LICENSE](LICENSE).
