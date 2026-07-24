# Architecture

One-page overview of how a question becomes a cited safety brief.

## Problem

Vehicle-safety information is authoritative but fragmented: recalls, crash-test ratings, VIN
attributes, and owner complaints live behind separate US NHTSA endpoints, with a structurally
different EU source (Safety Gate) alongside them. A driver asking "does my car have a recall, and
does it matter?" has to assemble that themselves.

The failure mode that matters is not incompleteness — it is a **confident wrong answer**. A
fabricated recall number, or a reassuring "no recalls found" produced during an upstream outage, is
worse than no answer. So the system is built to make every factual claim traceable to the source
record it came from, and to degrade visibly rather than silently.

## Constraints

- **Grounding.** Every safety fact must come from a tool result in the same turn. Recall campaign
  numbers are verified mechanically, not by model judgement.
- **Citation.** Every data claim carries an inline marker (`[recalls:1]`) that reconciles to a real
  executed tool call. Invented markers are dropped, not rendered.
- **Honesty about coverage.** US and EU data are never blended and are always labelled. EU Safety
  Gate coverage is partial and notification-driven; an empty result means "nothing found", never
  "no recalls exist".
- **Bounded spend.** A hard per-request cost cap and a bounded number of tool rounds; the loop stops
  and says so rather than spending indefinitely.
- **Bounded blast radius.** Per-IP rate limiting, explicit timeouts, and bounded retry on every
  upstream call.
- **Offline-testable.** The whole loop must be exercisable with no network and no API key.

## Components

| Component | Role |
|---|---|
| `agent/loop.py` | The investigation loop. Advertises the registry to Claude, dispatches tool calls, tags each result with a citation marker, enforces the round and cost caps, and reconciles markers into structured citations. |
| `agent/prompts.py` | `SYSTEM_PROMPT` — the behavioural contract: citation protocol, tool discipline, jurisdiction labelling, refusal and safety-caution rules. The golden set grades exactly these behaviours. |
| `tools/registry.py` | The seam. Binds each tool's schema to its async handler; `TOOL_SCHEMAS` + `dispatch(name, args)` are all the loop knows. Adding a source is a one-line append. |
| `tools/schemas.py` | Anthropic tool-use JSON schemas — self-contained descriptions, since they are all Claude sees. |
| `tools/nhtsa.py` | US client, imported as a **library** from the published `vehicle-safety-mcp` package so trimming and resilience logic cannot drift between the agent and the MCP server. |
| `tools/eu_safety_gate.py` | EU client (ADR 002). Consumes Safety Gate's XML search export, filters to motor vehicles, and mirrors the NHTSA client's degradation contract. |
| `core/` | Typed settings, token→USD cost estimation, JSON-lines logging, and a startup key preflight so a bad key fails once, clearly. |
| `api/` | FastAPI surface: `POST /ask`, `GET /healthz`, per-IP rate limiting. |
| `evals/` | The golden set and the harness that grades it — the layer that decides whether any of the above got better. |

## Data flow

```
question
  │
  ├─ POST /ask  (rate-limited, cost-capped)
  │
  ▼
run_agent ──► Claude (tools = TOOL_SCHEMAS, adaptive thinking)
  │                │
  │                ├─ stop_reason == tool_use ──► registry.dispatch(name, args)
  │                │        │
  │                │        ├─ NHTSA / Safety Gate call (timeout, bounded retry)
  │                │        └─ unreachable ──► {"available": false, ...}  (relayed, not hidden)
  │                │
  │                ◄─ tool_result tagged "[cite as recalls:1]" + trimmed JSON
  │                     (loops until a final answer, the round cap, or the cost cap)
  ▼
final answer
  │
  ├─ markers reconciled against executed calls ──► citations[]  (invented markers dropped)
  └─ raw tool_results returned as provenance
        │
        ▼
   eval harness: deterministic grounding veto + LLM-as-judge
```

The loop returns `{answer, citations, tool_calls, tool_results, usage}`. `/ask` serves the first
three; `tool_results` exists as **ground truth for grading** — it is what lets the harness verify
mechanically that every campaign number in an answer was actually retrieved.

## Grading

Two independent layers, deliberately asymmetric in what they are trusted with:

- **Deterministic** (offline, no API) — required facts present, forbidden patterns absent, and every
  recall campaign number **grounded** in a tool result from the same turn. This layer holds the tool
  results, so it is the only one that *can* verify grounding.
- **LLM-as-judge** — grades behaviour that string matching cannot: refusal quality, safety
  caveats, asking for clarification.

Each item resolves to `pass | fail | judge_error`. Judge errors are excluded from the pass-rate
denominator, and items whose tools returned `available:false` are tagged `infra_degraded` — an
upstream outage is never counted as an agent failure.

The rationale for that split is in [`POSTMORTEM.md`](POSTMORTEM.md): the judge was once asked to spot
invented recall numbers, could not see the tool results, and failed a correct answer for being more
complete than its own notes.

## Key decisions

Rationale lives in Architecture Decision Records — see [`docs/decisions/`](docs/decisions/):

- [001 — Evals before agent](docs/decisions/001-evals-before-agent.md) *(Accepted)* — the golden set
  defines a good brief before any agent code is written.
- [002 — EU recall data sources](docs/decisions/002-eu-data-sources.md) *(Proposed)* — Safety Gate
  first; KBA and other national sources deferred.
