# 001 — Evals before agent

- **Status:** Accepted
- **Date:** 2026-07-17

## Context

The agent does not exist yet. Not a single tool call, prompt, or planning loop has
been written. That is precisely the moment this decision has to be made, because the
easy path from here is to start writing agent code and judge it by vibes — "the answer
looks good" — which is exactly how a safety-adjacent system accumulates confident,
unverifiable wrongness.

This domain punishes that. A vehicle-safety brief that invents a recall campaign number,
misreports a crash-test rating, or says "yes, it's safe to keep driving" with an open
fuel-pump recall is not a cosmetic bug — it is the failure mode. The ground truth is
public and checkable (NHTSA APIs), so there is no excuse for grading on impressions.

We also have scope we are deliberately *not* building yet (EU RAPEX/KBA, Euro NCAP RAG).
Without a definition of correct behavior, "we don't have EU data yet" would be a bug
report instead of the correct, honest answer it should be today.

## Decision

Define correctness first, in code, as a graded golden set — then build the agent to pass
it.

- `evals/golden_set.yaml`: 25 items across six categories (recall lookup, VIN decode,
  crash-rating comparison, complaint analysis, out-of-scope refusal, safety-critical
  caution, ambiguity handling). Every data-backed fact is pinned to live NHTSA values
  with a `retrieved_on` date; behavioral items encode what the system must decline,
  caveat, or clarify.
- `evals/run_evals.py`: scores each item deterministically (exact facts / forbidden
  patterns) *and* with an LLM-as-judge (`claude-sonnet-4-6`) for the behavioral
  categories, and writes a dated results file to `evals/results/`.
- The eval set is the contract. New capabilities land with new eval items; regressions
  are caught by a falling pass rate, not by someone noticing later.

## Consequences

- **The first baseline run scores ~0%, and that is the point.** The answer function is a
  stub, so every item fails. Committing that 0% results file is the honest starting line —
  it makes every future point of progress a real, measured delta instead of a claim.
- Building the agent now has an unambiguous target: make the pass rate go up without
  gaming the rubric. "Done" is defined before the work starts.
- There is upfront cost — authoring and maintaining graded evals, and re-pinning
  ground truth as NHTSA data drifts (counts grow; ratings get added). Campaign numbers
  are treated as stable anchors and counts as floors to keep this maintenance bounded.
- The judge adds a per-run API cost and a dependency on model behavior; deterministic
  checks are the cheap first line and can veto the judge, so day-to-day iteration does
  not require the judge at all (`--no-judge`).
- Honesty is now gradeable: "I only have US data" is a *passing* answer for an EU-only
  vehicle, not a gap to paper over.
