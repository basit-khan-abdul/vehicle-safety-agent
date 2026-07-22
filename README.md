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
accuracy — so changes are measured, not guessed at. The first EU source — the EU's official
**Safety Gate** recall database — is now live alongside NHTSA, with US ↔ EU cross-referencing;
further national sources (KBA) and retrieval-augmented generation over Euro NCAP test protocols
come next. A TypeScript frontend and a public deployment come after the core is trustworthy.

## Architecture

> Diagram placeholder. See [ARCHITECTURE.md](ARCHITECTURE.md) for the written breakdown
> (Problem / Constraints / Components / Data flow / Key decisions).

<!-- TODO: architecture diagram — agent loop, tools, data sources, cited-brief output. -->

## Eval results

Populated from [`evals/results/`](evals/results/). The real agent (Claude tool-use loop over
live NHTSA data) graded by a deterministic fact-check plus an LLM-as-judge:

| date | run | eval set | model | pass rate | notes |
|------|-----|----------|-------|-----------|-------|
| 2026-07-21 | baseline | v0.1.0 | `claude-sonnet-4-6` | **12/25 (48%)** | First live baseline. `vin_decode` (0/3) and `comparison` (0/4) were depressed by an intermittent NHTSA ratings/recalls-host outage during the run — the agent correctly refused to fabricate; the judge scored missing facts as fails. [`baseline.md`](evals/results/2026-07-21-baseline.md) |
| 2026-07-21 | post-fixes-1 | v0.1.0 | `claude-sonnet-4-6` | **22/25 (88%)** | Re-run on healthy NHTSA + one grader fix. **+10, but honestly attributed:** +8 is NHTSA recovering (vin_decode 0→3, comparison 0→4, rec_04), +1 is the earlier saf_01 grader fix, and only **+1 is this change** (oos_02 negation guard). [`post-fixes-1.md`](evals/results/2026-07-21-post-fixes-1.md) |
| 2026-07-22 | eu-slice-1 | v0.2.0 | `claude-sonnet-4-6` | **3/4 scored — true 4/4** | EU-only validation of the new **Safety Gate** slice (4 of 28 items; the 24 US items were not re-scored). `eu_03` (VW ID.3 — now answered from EU data instead of refused) and `eu_xref_01` (US ↔ EU cross-reference) both pass. `eu_01`'s judge fail is a **verified false-positive**: every case number it called "invented" was in the tool result — the rec_05 pattern recurring for EU. [`eu-slice-1.md`](evals/results/2026-07-22-eu-slice-1.md) |

Per-category (baseline → post-fixes-1):

| category | baseline | post-fixes-1 | what moved it |
|----------|----------|--------------|---------------|
| complaint_analysis | 3/3 | 3/3 | — |
| out_of_scope_refusal | 3/4 | 4/4 | **grader fix this change** (oos_02 negation guard) |
| safety_critical_caution | 2/3 | 3/3 | prior grader fix (saf_01, commit `9eb389c`) |
| us_recall_lookup | 3/6 | 4/6* | NHTSA recovery; rec_05's fail was a **grader false-positive** (corrected — true 5/6), rec_06 hit a mid-run outage |
| ambiguous | 1/2 | 1/2 | amb_02 fails on a judge-side connection error (agent answer is correct) |
| vin_decode | 0/3 | 3/3 | NHTSA recovery (not a code change) |
| comparison | 0/4 | 4/4 | NHTSA recovery (not a code change) |

The grader fix in `post-fixes-1` moved exactly one category on its own merits
(`out_of_scope_refusal`, via oos_02); the rest of the jump is infrastructure recovery and a
previously-shipped fix. No category regressed.

*\*The `post-fixes-1` run scored rec_05 as a fail on a supposed hallucination; this was later
shown to be a **judge false-positive** and fixed.* The judge never sees tool results, so when the
agent correctly returned all 11 real NHTSA campaigns for the 2018 Jeep Grand Cherokee, the judge —
whose notes named only 4 — flagged the other 7 real campaigns as "invented." Grounding now lives in
the deterministic layer, which holds the tool results as ground truth: every recall-number token in
an answer must appear in a tool result from the same turn, or the item is vetoed. A genuine
hallucination is now structurally caught; a real-but-unlisted campaign is not. rec_05 re-verified
`pass` for the right reason (corrected true score: **23/25**). Citation accuracy is not yet scored as
a standalone metric; the harness grades required facts present, forbidden claims absent, recall-number
grounding, and judge verdict.

The `eu-slice-1` row is the EU-only subset (`--category eu_recall_lookup`) of the v0.2.0 set, run on
its own to validate the new Safety Gate capability under a tight API budget; a full-suite healthy
re-run across all 28 items (US + EU) is pending and will be added as its own row.

## Status

**US + EU live; hallucination guard and infra/judge-aware grading in place.** The agent investigates
both US **NHTSA** and EU **Safety Gate** recalls: a Claude tool-use loop with adaptive extended
thinking turns a question into a cited, jurisdiction-labelled brief, served over `POST /ask` with
per-request cost and per-IP rate caps. It never blends the two markets, labels every result by
jurisdiction, and now answers EU-only vehicles (e.g. VW ID.3) from Safety Gate instead of refusing.
The tool layer is wired to [`vehicle-safety-mcp`](https://github.com/basit-khan-abdul/vehicle-safety-mcp)
v0.2.0 (VIN decode, recalls, NCAP ratings, complaints), reusing its resilient HTTP client (timeouts,
bounded retry, honest degradation) as-is; the EU Safety Gate client mirrors the same contract.

Three properties are enforced, not hoped for:

- **Grounding is a deterministic veto.** Every NHTSA campaign-number token in an answer must appear in
  a tool result from the same turn, or the item is failed — a genuine hallucination is structurally
  caught, a real-but-unlisted campaign is not. An offline regression test freezes this on every push;
  extending the same veto to EU case numbers is the next grader step.
- **Infra and judge noise are categorised, not scored as agent failures.** A tool result carrying
  `available:false` tags the item `infra_degraded`; a judge that still errors after bounded retries
  marks the item `judge_error` and is excluded from the pass-rate denominator (shown as "N excluded").
  A run also preflights NHTSA and warns loudly at the top when upstream is down. An outage or a flaky
  judge can no longer masquerade as an agent fault.
- **Pass rates are reported on healthy infrastructure, with honest attribution.** The **12/25 (48%)**
  live baseline was taken during an NHTSA outage; the healthy re-run is **22/25 (88%)** (true **23/25**
  after a corrected judge false-positive), and the table above breaks the delta down — most of it is
  infrastructure recovery, not code.

Tests split into offline unit (mocked transport, Python 3.11 + 3.12 in CI) and live suites, with a
weekly contract-drift job; a startup preflight verifies the `ANTHROPIC_API_KEY` with one minimal call
so a missing/invalid key fails once, clearly, instead of on every question. **Next up: broaden EU
coverage** — KBA and other national sources per [ADR 002](docs/decisions/002-eu-data-sources.md), plus
a full-suite healthy re-run across all 28 v0.2.0 items.

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

1. **US recall slice** ✅ — agent investigates NHTSA recalls / ratings / complaints via
   `vehicle-safety-mcp` and produces a cited brief, graded against the eval set.
2. **EU cross-reference** *(first source live)* — EU **Safety Gate** recalls integrated with
   US ↔ EU cross-referencing; KBA and other national sources next (see
   [ADR 002](docs/decisions/002-eu-data-sources.md)).
3. **RAG over NCAP docs** — retrieval-augmented answers grounded in Euro NCAP protocols.
4. **TypeScript frontend** — a UI over the agent (see [`frontend/`](frontend/)).
5. **Public deployment** — hosted, rate- and cost-capped, publicly reachable.

## License

MIT — see [LICENSE](LICENSE).
