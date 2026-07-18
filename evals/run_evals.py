#!/usr/bin/env python3
"""Golden-set eval harness for vehicle-safety-agent.

Loads ``evals/golden_set.yaml``, runs each question through a pluggable
``answer_fn(question) -> {answer, citations, tool_calls}``, and scores every item
two independent ways:

  1. Deterministic fact-check (offline, no API): every ``required_fact`` must be
     present (string / any_of / all_of / regex) and no ``forbidden_patterns`` may
     match. Fast and cheap — the layer you iterate against.
  2. LLM-as-judge (``claude-sonnet-4-6``): grades ``required_facts`` +
     ``forbidden_behaviors`` against ``grading_notes`` with a strict rubric. This
     is what carries the behavioral categories (refusal, caution, ambiguous) that
     string matching cannot judge.

Pass logic per item:
  * If the judge ran:   pass  == judge says "pass"  AND deterministic did not veto
                        (a missing hard fact or a matched forbidden pattern vetoes).
  * If the judge was skipped (no ANTHROPIC_API_KEY / SDK): pass == the deterministic
    check *affirmatively* passed. Items with no deterministic criteria cannot be
    confirmed offline and are counted as "unverified" (not a pass) so the report
    never over-credits a run the judge never saw.

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
import re
import sys
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
    "out_of_scope_refusal": 4,
    "safety_critical_caution": 3,
    "ambiguous": 2,
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
        }
    return {
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "tool_calls": result.get("tool_calls", []),
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


def deterministic_check(item: dict, answer: str) -> dict:
    required = item.get("required_facts") or []
    patterns = item.get("forbidden_patterns") or []
    missing = [_fact_label(f) for f in required if not _fact_present(f, answer)]
    triggered = [p for p in patterns if re.search(p, answer, re.IGNORECASE)]

    if missing or triggered:
        status = "fail"
    elif required:
        status = "pass"  # affirmatively confirmed at least one hard fact
    else:
        status = "insufficient"  # nothing checkable offline; needs the judge

    return {
        "status": status,
        "missing_facts": missing,
        "forbidden_matched": triggered,
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
    try:
        message = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=1024,
            temperature=0,
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(rubric, indent=2, default=str)}],
        )
    except Exception as exc:  # pragma: no cover - network/runtime guard
        return {"passed": False, "error": f"judge call failed: {exc}", "reasoning": "", "raw": {}}

    text = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
    data = _extract_json(text)
    if not data:
        return {"passed": False, "error": "unparseable judge output", "reasoning": text[:200], "raw": {}}
    return {
        "passed": data.get("verdict") == "pass",
        "reasoning": data.get("reasoning", ""),
        "missing": data.get("required_facts_missing", []),
        "forbidden_triggered": data.get("forbidden_triggered", []),
        "raw": data,
    }


# ---------------------------------------------------------------------------
# Scoring one item
# ---------------------------------------------------------------------------
def score_item(item: dict, judge_client) -> dict:
    result = answer_fn(item["question"])
    answer = result.get("answer", "")
    det = deterministic_check(item, answer)

    if judge_client is not None:
        judge = judge_check(item, answer, judge_client)
        passed = judge["passed"] and det["status"] != "fail"
    else:
        judge = None
        passed = det["status"] == "pass"

    return {
        "id": item["id"],
        "category": item["category"],
        "question": item["question"],
        "answer": answer,
        "deterministic": det,
        "judge": judge,
        "passed": passed,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _pct(n: int, d: int) -> str:
    return f"{(100 * n / d):.0f}%" if d else "—"


def build_report(rows: list[dict], meta: dict) -> str:
    total = len(rows)
    passed = sum(r["passed"] for r in rows)

    lines: list[str] = []
    lines.append(f"# Eval results — {meta['date']} — {meta['label']}")
    lines.append("")
    lines.append(f"- **Answer source:** `{meta['answer_source']}`")
    lines.append(f"- **Judge:** {meta['judge_status']}")
    lines.append(f"- **Golden set:** v{meta['golden_version']} (retrieved {meta['golden_retrieved_on']})")
    lines.append(f"- **Items run:** {total}" + (f" (limit {meta['limit']})" if meta.get("limit") else ""))
    lines.append("")
    lines.append(f"## Overall: {passed}/{total} passed ({_pct(passed, total)})")
    lines.append("")

    # Per-category table
    lines.append("| Category | Items | Passed | Pass rate |")
    lines.append("|---|---|---|---|")
    for cat in CATEGORIES:
        crows = [r for r in rows if r["category"] == cat]
        if not crows:
            continue
        cp = sum(r["passed"] for r in crows)
        lines.append(f"| {cat} | {len(crows)} | {cp} | {_pct(cp, len(crows))} |")
    lines.append(f"| **Total** | **{total}** | **{passed}** | **{_pct(passed, total)}** |")
    lines.append("")

    failures = [r for r in rows if not r["passed"]]
    lines.append(f"## Failures ({len(failures)})")
    lines.append("")
    if not failures:
        lines.append("_None._")
    for r in failures:
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
        if r["judge"] is None:
            lines.append("- judge: _skipped_")
        else:
            j = r["judge"]
            if j.get("error"):
                lines.append(f"- judge: error — {j['error']}")
            else:
                lines.append(f"- judge: `{'pass' if j['passed'] else 'fail'}` — {j['reasoning']}")
        answer = r["answer"].replace("\n", " ").strip()
        if len(answer) > 600:
            answer = answer[:600] + "…"
        lines.append(f"- actual answer: {answer}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Run the vehicle-safety golden eval set.")
    parser.add_argument("--label", default="baseline-stub", help="run label (goes in the filename)")
    parser.add_argument("--limit", type=int, default=None, help="run only the first N items")
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

    items = data["items"]
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
    }
    report = build_report(rows, meta)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{date}-{args.label}.md"
    out_path.write_text(report)

    passed = sum(r["passed"] for r in rows)
    print(f"\nOverall: {passed}/{len(rows)} passed ({_pct(passed, len(rows))})")
    print(f"Wrote {out_path.relative_to(ROOT.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
