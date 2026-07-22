# Post-mortems

This file documents real failures and their fixes — grading, agent, or infrastructure.
Blameless, written after the fact, ending in the smallest change that stops the failure
from recurring.

---

## rec_05 — the grader hallucinated a hallucination

**When:** 2026-07-21, `post-fixes-1` eval run
**Class:** grading integrity (caught in evals, pre-ship — no user impact)
**Fix:** deterministic grounding veto (`bb0ed7b`), frozen by a regression test (`a123b06`)

### What happened
rec_05 ("recalls for the 2018 Jeep Grand Cherokee") was scored **fail** because the agent had
supposedly *invented* recall campaign numbers. The judge's note flagged seven campaigns as
fabricated.

The agent had done nothing wrong. It queried NHTSA, got back all 11 real campaigns for that
vehicle, and reported them. Every number it printed was present in the tool result from the same
turn. The **grader** was wrong, not the agent.

### Root cause
The LLM-as-judge never sees tool results. It scores the answer against its own notes, and its
notes named only 4 of the 11 real campaigns — so it treated the other 7 real-but-unlisted
campaigns as hallucinations and failed a correct answer.

That is the dangerous shape of the bug: **a grader that is less informed than the thing it grades
will punish the agent for being more complete than the answer key** — and, worse, would just as
happily *pass* a genuine hallucination whose invented number happened to match the judge's
expectation. The harness couldn't tell grounded from ungrounded, because the layer making the call
couldn't see the ground truth.

Two things helped it hide:
- An intermittent NHTSA outage was depressing several categories at the same time, so one extra
  "fail" didn't look anomalous.
- The deterministic and judge signals were collapsed into a single pass/fail, so a confident-but-
  wrong judge verdict had nothing to override it.

### The fix
Grounding was moved out of the judge's opinion and into a deterministic veto that treats the
**tool results as ground truth**:

- The agent loop now returns the tool results alongside the answer.
- Every recall-campaign-number token in the answer must appear verbatim in a tool result from the
  same turn. If one doesn't, the item fails — regardless of what the judge thought.
- A real-but-unlisted campaign (rec_05's case) is grounded, so it passes; an invented number is in
  no tool result, so it is caught. The judge's unverifiable "you invented a number" behavior was
  removed from the rubric — the judge cannot verify grounding and shouldn't pretend to.

rec_05 re-verified `pass` for the right reason; corrected true score 23/25.

### Why it won't come back
`backend/tests/unit/test_grounding_regression.py` freezes the behavior offline, on every push:
feed the agent a known set of campaign numbers and assert the answer contains those and **only**
those — a faithful answer passes with zero ungrounded tokens, a padded/invented number is flagged.
No network, no API key, no judge.

### What we learned
A grading harness must be **more reliable than the thing it grades**. When the grader is less
informed than the agent, its verdicts are noise dressed as signal. Ground truth belongs in the
deterministic layer that can actually see it; the judge is for what only a human-like reader can
assess — tone, refusal quality, caveats — not for facts a regex can check against the source.

### Still open
The same judge-blindness recurred for EU in `eu-slice-1` (eu_01): the deterministic veto does not
yet cover EU Safety Gate case-number formats, so nothing overrode the wrong judge verdict there.
Extending grounding to EU case numbers — and removing the parallel unverifiable judge behavior for
EU items — is the tracked next grader step.
