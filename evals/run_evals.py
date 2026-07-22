#!/usr/bin/env python3
"""Golden-set eval harness for vehicle-safety-agent.

Loads ``evals/golden_set.yaml``, runs each question through a pluggable
``answer_fn(question) -> {answer, citations, tool_calls}``, and scores every item
two independent ways:

  1. Deterministic fact-check (offline, no API): every ``required_fact`` must be
     present (string / any_of / all_of / regex), no ``forbidden_patterns`` may
     match, and every recall campaign number in the answer must be *grounded* —
     present in a tool result from the same turn. Grounding lives here, not in the
     judge, because only this layer sees the tool results (ground truth); the judge
     asked to spot "invented" numbers with no source list will flag real-but-unlisted
     ones. Fast and cheap — the layer you iterate against.
  2. LLM-as-judge (``claude-sonnet-4-6``): grades ``required_facts`` +
     ``forbidden_behaviors`` against ``grading_notes`` with a strict rubric. This
     is what carries the behavioral categories (refusal, caution, ambiguous) that
     string matching cannot judge.

Each item resolves to one of three outcomes — pass | fail | judge_error:
  * If the judge ran:   pass == judge says "pass" AND deterministic did not veto
                        (a missing hard fact or a matched forbidden pattern vetoes).
                        If the judge could not return a verdict after bounded,
                        jittered retries, the item is ``judge_error`` — a THIRD
                        outcome excluded from the pass-rate denominator, because a
                        grader outage is not an agent failure.
  * If the judge was skipped (no ANTHROPIC_API_KEY / SDK): pass == the deterministic
    check *affirmatively* passed. Items with no deterministic criteria cannot be
    confirmed offline and are counted as "unverified" (not a pass) so the report
    never over-credits a run the judge never saw.

Two more reliability signals keep infrastructure noise from reading as agent
misses: each item is tagged ``infra_degraded`` when a tool returned the upstream
``available: false`` payload that turn (a NHTSA outage, not an agent fault), and a
one-shot NHTSA preflight warns loudly — in the console and at the top of the
results file — when the upstream is already down at the start of a run.

Writes ``evals/results/{date}-{label}.md``.

Examples:
  uv run --with pyyaml --with anthropic python evals/run_evals.py --label baseline-stub
  uv run --with pyyaml python evals/run_evals.py --no-judge --limit 5
  uv run --with pyyaml python evals/run_evals.py --validate-only
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import re
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - env guard
    sys.exit("pyyaml is required. Run via: uv run --with pyyaml python evals/run_evals.py ...")

ROOT = Path(__file__).resolve().parent
GOLDEN_PATH = ROOT / "golden_set.yaml"
RESULTS_DIR = ROOT / "results"
JUDGE_MODEL = "claude-sonnet-4-6"

# Make the backend `app` package importable (backend/ is the source root, same
# convention as pyproject's pytest pythonpath and the smoke script).
sys.path.insert(0, str(ROOT.parent / "backend"))

EXPECTED_COUNTS = {
    "us_recall_lookup": 6,
    "vin_decode": 3,
    "comparison": 4,
    "complaint_analysis": 3,
    "out_of_scope_refusal": 3,  # v0.2.0: the VW ID.3 item graduated to eu_recall_lookup
    "safety_critical_caution": 3,
    "ambiguous": 2,
    "eu_recall_lookup": 4,  # v0.2.0: EU Safety Gate slice (ADR 002)
}
CATEGORIES = list(EXPECTED_COUNTS)


# ---------------------------------------------------------------------------
# answer_fn — the pluggable seam. Runs the real investigation loop. The agent
# returns {"answer": str, "citations": list, "tool_calls": list, "usage": dict};
# the harness reads the first three.
# ---------------------------------------------------------------------------
def answer_fn(question: str) -> dict:
    """Real vehicle-safety agent — runs the tool-use loop for one question."""
    try:
        import asyncio

        from app.agent.loop import run_agent
        from app.core.config import get_settings

        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        result = asyncio.run(run_agent(question, settings=settings))
    except Exception as exc:  # keep the harness resilient — surface, don't crash
        return {
            "answer": f"agent error: {type(exc).__name__}: {exc}",
            "citations": [],
            "tool_calls": [],
            "tool_results": [],
        }
    return {
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "tool_calls": result.get("tool_calls", []),
        "tool_results": result.get("tool_results", []),
    }


# ---------------------------------------------------------------------------
# Loading + validation
# ---------------------------------------------------------------------------
def load_golden() -> dict:
    with GOLDEN_PATH.open() as fh:
        return yaml.safe_load(fh)


def validate(data: dict) -> list[str]:
    """Return a list of schema errors (empty == valid)."""
    errors: list[str] = []
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return ["'items' is missing or empty"]

    seen_ids: set[str] = set()
    counts: dict[str, int] = {c: 0 for c in CATEGORIES}
    for i, item in enumerate(items):
        where = f"item[{i}]"
        iid = item.get("id")
        if not iid:
            errors.append(f"{where}: missing 'id'")
        else:
            where = iid
            if iid in seen_ids:
                errors.append(f"{where}: duplicate id")
            seen_ids.add(iid)
        cat = item.get("category")
        if cat not in EXPECTED_COUNTS:
            errors.append(f"{where}: category '{cat}' is not one of {CATEGORIES}")
        else:
            counts[cat] += 1
        if not item.get("question"):
            errors.append(f"{where}: missing 'question'")
        for key in ("required_facts", "forbidden_behaviors"):
            if not isinstance(item.get(key), list):
                errors.append(f"{where}: '{key}' must be a list")
        if not isinstance(item.get("grading_notes", ""), str):
            errors.append(f"{where}: 'grading_notes' must be a string")

    for cat, want in EXPECTED_COUNTS.items():
        if counts.get(cat, 0) != want:
            errors.append(f"category '{cat}': expected {want} items, found {counts.get(cat, 0)}")
    return errors


# ---------------------------------------------------------------------------
# Deterministic fact-check
# ---------------------------------------------------------------------------

# A NHTSA recall campaign number, e.g. 21V215000 or 18E097000. These are
# safety-critical, high-stakes tokens: every one that appears in an answer MUST
# have come from a tool result in the same turn. The LLM judge cannot verify
# this — it never sees the tool results — so grounding is enforced here, against
# the actual data the tools returned. An ungrounded number is a fabrication.
RECALL_NUMBER_RE = re.compile(r"\b\d{2}[VE]\d{6}\b", re.IGNORECASE)


def _ungrounded_recall_numbers(answer: str, tool_results: list | None) -> list[str]:
    """Recall-number tokens in the answer with no match in this turn's tool results."""
    corpus = json.dumps(tool_results or [], default=str).upper()
    ungrounded: list[str] = []
    for tok in RECALL_NUMBER_RE.findall(answer):
        up = tok.upper()
        if up not in corpus and up not in ungrounded:
            ungrounded.append(up)
    return ungrounded


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _fact_present(fact, answer: str) -> bool:
    norm_ans = _norm(answer)
    if isinstance(fact, str):
        return _norm(fact) in norm_ans
    if isinstance(fact, dict):
        if "any_of" in fact:
            return any(_norm(x) in norm_ans for x in fact["any_of"])
        if "all_of" in fact:
            return all(_norm(x) in norm_ans for x in fact["all_of"])
        if "regex" in fact:
            return re.search(fact["regex"], answer, re.IGNORECASE) is not None
    return False


def _fact_label(fact) -> str:
    if isinstance(fact, str):
        return fact
    if isinstance(fact, dict):
        for key in ("any_of", "all_of", "regex"):
            if key in fact:
                return f"{key}:{fact[key]}"
    return str(fact)


def deterministic_check(item: dict, answer: str, tool_results: list | None = None) -> dict:
    required = item.get("required_facts") or []
    patterns = item.get("forbidden_patterns") or []
    missing = [_fact_label(f) for f in required if not _fact_present(f, answer)]
    triggered = [p for p in patterns if re.search(p, answer, re.IGNORECASE)]
    ungrounded = _ungrounded_recall_numbers(answer, tool_results)

    if missing or triggered or ungrounded:
        status = "fail"
    elif required:
        status = "pass"  # affirmatively confirmed at least one hard fact
    else:
        status = "insufficient"  # nothing checkable offline; needs the judge

    return {
        "status": status,
        "missing_facts": missing,
        "forbidden_matched": triggered,
        "ungrounded_numbers": ungrounded,
        "facts_total": len(required),
        "facts_found": len(required) - len(missing),
    }


# ---------------------------------------------------------------------------
# LLM-as-judge (claude-sonnet-4-6)
# ---------------------------------------------------------------------------
JUDGE_SYSTEM = """You are a strict grader for a vehicle-safety information agent that \
answers questions using US NHTSA data and must cite its sources.

You receive a JSON object with: question, required_facts, forbidden_behaviors, \
grading_notes, and candidate_answer. Grade ONLY the candidate_answer against that \
rubric. grading_notes is authoritative.

Rules:
- Every required_fact must be present or clearly entailed by the answer. Some entries \
are objects ({any_of/all_of/regex}); treat them as satisfied if their intent is met.
- If ANY forbidden_behavior occurs, the verdict is "fail".
- For behavioral categories (refusal, safety caution, ambiguous) correctness is about \
BEHAVIOR (declining, caveating, citing the official remedy/channel, asking for \
clarification), not fluent prose. A confident but unsupported or unsafe answer fails.
- Do not reward an answer for being well written. Do not invent facts on its behalf.

Respond with ONLY a JSON object, no prose, no code fence:
{"verdict":"pass"|"fail","required_facts_present":[...],"required_facts_missing":[...],\
"forbidden_triggered":[...],"reasoning":"<= 2 sentences"}"""


def make_judge():
    """Return (client, skip_reason). client is None when the judge can't run."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None, "no ANTHROPIC_API_KEY in environment"
    try:
        import anthropic
    except ImportError:
        return None, "anthropic SDK not installed (add --with anthropic)"
    return anthropic.Anthropic(), None


# Judge retry policy (env-tunable) — mirrors the NHTSA client's bounded, jittered
# backoff so the grader is at least as resilient as the data source it grades. A
# transient judge outage (connection/timeout/rate-limit/5xx) is retried; if it
# still fails, the item is marked `judge_error` and excluded from the pass-rate
# denominator — a judge outage is never counted as an agent failure.
_JUDGE_MAX_ATTEMPTS = int(os.getenv("JUDGE_MAX_ATTEMPTS", "3"))
_JUDGE_BACKOFF_BASE = float(os.getenv("JUDGE_BACKOFF_BASE", "0.5"))
_JUDGE_BACKOFF_CAP = float(os.getenv("JUDGE_BACKOFF_CAP", "8.0"))


def _judge_sleep(seconds: float) -> None:
    """Backoff sleep. Indirected so tests can neutralise the wait."""
    time.sleep(seconds)


def _judge_retryable(exc: Exception) -> bool:
    """Retry only transient judge failures: connection errors, timeouts, rate
    limits, and 5xx. A 4xx (bad request / auth) won't fix itself — fail fast."""
    try:
        import anthropic

        transient = (
            anthropic.APIConnectionError,  # covers APITimeoutError (subclass)
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        )
        if isinstance(exc, transient):
            return True
    except ImportError:  # pragma: no cover - judge only runs with the SDK present
        pass
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status >= 500


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def judge_check(item: dict, answer: str, client) -> dict:
    rubric = {
        "question": item["question"],
        "required_facts": item.get("required_facts", []),
        "forbidden_behaviors": item.get("forbidden_behaviors", []),
        "grading_notes": item.get("grading_notes", ""),
        "candidate_answer": answer,
    }
    messages = [{"role": "user", "content": json.dumps(rubric, indent=2, default=str)}]

    # Bounded, jittered retry (same discipline as the NHTSA client). A transient
    # judge outage must not masquerade as an agent failure, so on exhaustion we
    # return an `errored` verdict — scored as `judge_error`, not `fail`.
    message = None
    for attempt in range(1, _JUDGE_MAX_ATTEMPTS + 1):
        try:
            message = client.messages.create(
                model=JUDGE_MODEL,
                max_tokens=1024,
                temperature=0,
                system=JUDGE_SYSTEM,
                messages=messages,
            )
            break
        except Exception as exc:  # network/runtime guard
            if not _judge_retryable(exc) or attempt == _JUDGE_MAX_ATTEMPTS:
                return {
                    "passed": None,
                    "errored": True,
                    "error": f"judge call failed after {attempt} attempt(s): {exc}",
                    "reasoning": "",
                    "raw": {},
                }
            ceiling = min(_JUDGE_BACKOFF_CAP, _JUDGE_BACKOFF_BASE * 2 ** (attempt - 1))
            _judge_sleep(random.uniform(0, ceiling))

    text = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
    data = _extract_json(text)
    if not data:
        return {
            "passed": False,
            "errored": False,
            "error": "unparseable judge output",
            "reasoning": text[:200],
            "raw": {},
        }
    return {
        "passed": data.get("verdict") == "pass",
        "errored": False,
        "reasoning": data.get("reasoning", ""),
        "missing": data.get("required_facts_missing", []),
        "forbidden_triggered": data.get("forbidden_triggered", []),
        "raw": data,
    }


# ---------------------------------------------------------------------------
# NHTSA preflight — one cheap call so an upstream outage is flagged loudly at the
# top of a run, instead of being silently mistaken for an agent baseline.
# ---------------------------------------------------------------------------
def nhtsa_preflight() -> dict:
    """Probe NHTSA once with a known-good recall lookup. Never raises.

    Returns ``{"ok": bool, "detail": str}``. A down NHTSA warns (recall / rating /
    VIN categories will be unscorable) but does not abort — behavioral categories
    (refusal, caution, ambiguous) are still worth running.
    """
    try:
        import asyncio

        from app.tools import nhtsa

        resp = asyncio.run(nhtsa.get_recalls("Honda", "Accord", 2020))
    except Exception as exc:  # network/import guard — probe must never crash the run
        return {"ok": False, "detail": f"preflight call raised {type(exc).__name__}: {exc}"}
    if isinstance(resp, dict) and resp.get("available") is False:
        detail = resp.get("detail") or resp.get("error") or "NHTSA returned available: false"
        return {"ok": False, "detail": detail}
    return {"ok": True, "detail": "NHTSA reachable"}


# ---------------------------------------------------------------------------
# Scoring one item
# ---------------------------------------------------------------------------
def score_item(item: dict, judge_client) -> dict:
    result = answer_fn(item["question"])
    answer = result.get("answer", "")
    tool_results = result.get("tool_results", [])
    det = deterministic_check(item, answer, tool_results)

    # An item is `infra_degraded` if any tool this turn returned the upstream
    # degradation payload (`available: false`). This is orthogonal to pass/fail
    # (the agent may correctly refuse and still miss the required facts) — it
    # tags the *cause* so an NHTSA outage is not read as an agent fault.
    infra_degraded = any(
        isinstance(r, dict) and r.get("available") is False for r in tool_results
    )

    # Outcome is a three-way: pass | fail | judge_error. judge_error means the
    # judge could not return a verdict after retries; it is excluded from the
    # pass-rate denominator downstream, never counted as an agent failure.
    if judge_client is not None:
        judge = judge_check(item, answer, judge_client)
        if judge.get("errored"):
            passed = False
            outcome = "judge_error"
        else:
            passed = judge["passed"] and det["status"] != "fail"
            outcome = "pass" if passed else "fail"
    else:
        judge = None
        passed = det["status"] == "pass"
        outcome = "pass" if passed else "fail"

    return {
        "id": item["id"],
        "category": item["category"],
        "question": item["question"],
        "answer": answer,
        "deterministic": det,
        "judge": judge,
        "passed": passed,
        "outcome": outcome,
        "infra_degraded": infra_degraded,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _pct(n: int, d: int) -> str:
    return f"{(100 * n / d):.0f}%" if d else "—"


def _render_item_detail(lines: list[str], r: dict) -> None:
    """Append the shared per-item detail block (deterministic + judge + answer)."""
    det = r["deterministic"]
    lines.append(f"### {r['id']} · {r['category']}")
    lines.append(f"**Q:** {r['question']}")
    lines.append("")
    lines.append(f"- deterministic: `{det['status']}` "
                 f"(facts {det['facts_found']}/{det['facts_total']})")
    if det["missing_facts"]:
        lines.append(f"  - missing facts: {det['missing_facts']}")
    if det["forbidden_matched"]:
        lines.append(f"  - forbidden pattern matched: {det['forbidden_matched']}")
    if det.get("ungrounded_numbers"):
        lines.append(
            "  - ungrounded recall numbers (in answer, not in any tool result): "
            f"{det['ungrounded_numbers']}"
        )
    if r["judge"] is None:
        lines.append("- judge: _skipped_")
    else:
        j = r["judge"]
        if j.get("errored") or j.get("error"):
            lines.append(f"- judge: error — {j.get('error', '')}")
        else:
            lines.append(f"- judge: `{'pass' if j['passed'] else 'fail'}` — {j['reasoning']}")
    if r.get("infra_degraded"):
        lines.append(
            "- infra: `degraded` — a tool returned `available: false` this turn "
            "(NHTSA upstream outage, not an agent fault)"
        )
    answer = r["answer"].replace("\n", " ").strip()
    if len(answer) > 600:
        answer = answer[:600] + "…"
    lines.append(f"- actual answer: {answer}")
    lines.append("")


def build_report(rows: list[dict], meta: dict) -> str:
    total = len(rows)
    excluded = [r for r in rows if r["outcome"] == "judge_error"]
    graded = [r for r in rows if r["outcome"] != "judge_error"]
    denom = len(graded)
    passed = sum(r["outcome"] == "pass" for r in rows)

    lines: list[str] = []
    lines.append(f"# Eval results — {meta['date']} — {meta['label']}")
    lines.append("")
    lines.append(f"- **Answer source:** `{meta['answer_source']}`")
    lines.append(f"- **Judge:** {meta['judge_status']}")
    lines.append(f"- **Golden set:** v{meta['golden_version']} (retrieved {meta['golden_retrieved_on']})")
    lines.append(f"- **Items run:** {total}" + (f" (limit {meta['limit']})" if meta.get("limit") else ""))
    lines.append("")

    # Loud, in-file NHTSA-outage banner so an infrastructure baseline can never
    # be mistaken for an agent baseline by a later reader of this file.
    pf = meta.get("nhtsa_preflight")
    if pf and not pf.get("ok"):
        lines.append(
            f"> ⚠️ **NHTSA was unreachable at the start of this run** — {pf.get('detail', '')} "
            "Recall / rating / VIN categories were **unscorable against live data**; treat this "
            "as an *infrastructure* baseline, not an agent baseline, and rerun once NHTSA recovers."
        )
        lines.append("")

    excl_note = f" ({len(excluded)} excluded: judge error)" if excluded else ""
    lines.append(f"## Overall: {passed}/{denom} passed ({_pct(passed, denom)}){excl_note}")
    lines.append("")

    # Per-category table. Judge-error items are excluded from that category's
    # denominator, mirroring the overall pass-rate math.
    lines.append("| Category | Items | Excluded | Passed | Pass rate |")
    lines.append("|---|---|---|---|---|")
    for cat in CATEGORIES:
        crows = [r for r in rows if r["category"] == cat]
        if not crows:
            continue
        cex = sum(r["outcome"] == "judge_error" for r in crows)
        cp = sum(r["outcome"] == "pass" for r in crows)
        lines.append(f"| {cat} | {len(crows)} | {cex} | {cp} | {_pct(cp, len(crows) - cex)} |")
    lines.append(
        f"| **Total** | **{total}** | **{len(excluded)}** | **{passed}** | **{_pct(passed, denom)}** |"
    )
    lines.append("")

    failures = [r for r in rows if r["outcome"] == "fail"]
    infra_fails = [r for r in failures if r.get("infra_degraded")]
    lines.append(f"## Failures ({len(failures)})")
    lines.append("")
    if infra_fails:
        lines.append(
            f"_**{len(infra_fails)} of {len(failures)}** failure(s) were **upstream-unreachable** "
            "(a tool returned `available: false` that turn) — an NHTSA outage, not an agent fault._"
        )
        lines.append("")
    if not failures:
        lines.append("_None._")
        lines.append("")
    for r in failures:
        _render_item_detail(lines, r)

    # Excluded items are broken out separately so they are visibly NOT failures.
    if excluded:
        lines.append(f"## Excluded — judge error ({len(excluded)})")
        lines.append("")
        lines.append(
            "_Removed from the pass-rate denominator: the LLM judge failed to return a verdict "
            "after retries, so these items cannot be graded. A judge outage is never counted as "
            "an agent failure._"
        )
        lines.append("")
        for r in excluded:
            _render_item_detail(lines, r)

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Run the vehicle-safety golden eval set.")
    parser.add_argument("--label", default="baseline-stub", help="run label (goes in the filename)")
    parser.add_argument("--limit", type=int, default=None, help="run only the first N items")
    parser.add_argument(
        "--category",
        default=None,
        help="run only items in these categories (comma-separated). The full file is "
        "still validated first; this only narrows what is scored — useful for a "
        "cheap, targeted run of one new category.",
    )
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM-as-judge pass")
    parser.add_argument("--date", default=None, help="override the results date (YYYY-MM-DD)")
    parser.add_argument("--validate-only", action="store_true", help="validate the YAML and exit")
    args = parser.parse_args()

    data = load_golden()
    errors = validate(data)
    if errors:
        print("golden_set.yaml is INVALID:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 2
    print(f"golden_set.yaml valid: {len(data['items'])} items across {len(CATEGORIES)} categories.")
    if args.validate_only:
        return 0

    # Preflight: one minimal API call up front so a missing/invalid key fails
    # once, clearly, instead of surfacing as an error on all N questions.
    from app.core.config import get_settings
    from app.core.preflight import PreflightError, verify_anthropic_key

    try:
        verify_anthropic_key(get_settings())
    except PreflightError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 3
    print("Preflight: ANTHROPIC_API_KEY verified.")

    # NHTSA preflight: one cheap call up front. A down upstream is a WARNING, not
    # fatal — but a loud one, so an outage baseline is never mistaken for an agent
    # baseline (both in the console here and in the results file, via meta).
    nhtsa_pf = nhtsa_preflight()
    if nhtsa_pf["ok"]:
        print("Preflight: NHTSA reachable.")
    else:
        banner = "=" * 72
        print("\n" + banner, file=sys.stderr)
        print("WARNING: NHTSA UNREACHABLE AT START OF RUN.", file=sys.stderr)
        print(f"  {nhtsa_pf['detail']}", file=sys.stderr)
        print("  Recall / rating / VIN categories will be unscorable against live", file=sys.stderr)
        print("  data — this will read as an INFRASTRUCTURE baseline, not an agent", file=sys.stderr)
        print("  baseline. Consider rerunning once NHTSA recovers.", file=sys.stderr)
        print(banner + "\n", file=sys.stderr)

    items = data["items"]
    if args.category:
        wanted = {c.strip() for c in args.category.split(",")}
        unknown = wanted - set(CATEGORIES)
        if unknown:
            print(f"FATAL: unknown category/ies {sorted(unknown)}; valid: {CATEGORIES}", file=sys.stderr)
            return 2
        items = [it for it in items if it["category"] in wanted]
        print(f"Category filter {sorted(wanted)}: {len(items)} item(s) selected.")
    if args.limit:
        items = items[: args.limit]

    if args.no_judge:
        judge_client, judge_status = None, "disabled (--no-judge)"
    else:
        judge_client, skip_reason = make_judge()
        judge_status = f"{JUDGE_MODEL}" if judge_client else f"skipped — {skip_reason}"
    print(f"Judge: {judge_status}")

    rows = []
    for item in items:
        row = score_item(item, judge_client)
        mark = "PASS" if row["passed"] else "FAIL"
        print(f"  [{mark}] {row['id']} ({row['category']})")
        rows.append(row)

    date = args.date or datetime.date.today().isoformat()
    meta = {
        "date": date,
        "label": args.label,
        "answer_source": answer_fn.__doc__.splitlines()[0] if answer_fn.__doc__ else "answer_fn",
        "judge_status": judge_status,
        "golden_version": data.get("version", "?"),
        "golden_retrieved_on": data.get("retrieved_on", "?"),
        "limit": args.limit,
        "nhtsa_preflight": nhtsa_pf,
    }
    report = build_report(rows, meta)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{date}-{args.label}.md"
    out_path.write_text(report)

    passed = sum(r["outcome"] == "pass" for r in rows)
    excluded = sum(r["outcome"] == "judge_error" for r in rows)
    denom = len(rows) - excluded
    excl_note = f" ({excluded} excluded: judge error)" if excluded else ""
    print(f"\nOverall: {passed}/{denom} passed ({_pct(passed, denom)}){excl_note}")
    print(f"Wrote {out_path.relative_to(ROOT.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
