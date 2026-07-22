"""The investigation loop: one question in, one cited answer out.

A generic Anthropic tool-use loop over the tool registry. It advertises
``registry.TOOL_SCHEMAS`` to Claude, dispatches whatever tools Claude calls, and
feeds each result back tagged with a citation marker so the model can reference
it inline (``[recalls:1]``). After the answer is produced, the markers Claude
actually used are reconciled against the tools that ran to build structured
citations.

Guardrails:
- At most ``settings.max_tool_rounds`` tool-call rounds, then one forced final
  answer with tools withheld.
- A hard per-request cost cap: spend is estimated from cumulative usage tokens,
  and the loop aborts (returning a truthful "budget exceeded" answer) rather than
  making another expensive call.

The Anthropic client is injectable so the loop is unit-testable with a fake
client — no API key and no network required.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from anthropic import AsyncAnthropic

from app.agent.prompts import SYSTEM_PROMPT
from app.core.config import Settings
from app.core.cost import estimate_cost
from app.core.logging import log_event
from app.tools import registry

# Human-meaningful citation slugs per tool. The nth call of a tool becomes
# "<slug>:<n>" — e.g. the first get_recalls is "recalls:1".
_MARKER_SLUGS = {
    "decode_vin": "vin",
    "check_vin_recalls": "vin_recalls",
    "get_recalls": "recalls",
    "get_safety_ratings": "ratings",
    "get_complaints": "complaints",
    "search_eu_recalls": "eu_recalls",
}
_MARKER_RE = re.compile(r"\[([a-z_]+:\d+)\]")


def _assign_marker(tool_name: str, counts: dict[str, int]) -> str:
    slug = _MARKER_SLUGS.get(tool_name, tool_name)
    counts[slug] = counts.get(slug, 0) + 1
    return f"{slug}:{counts[slug]}"


def _text_of(content: list[Any]) -> str:
    """Concatenate the text blocks of an assistant message."""
    return "\n".join(
        block.text for block in content if getattr(block, "type", None) == "text"
    ).strip()


def _is_available(result: dict[str, Any]) -> bool:
    """Whether a tool result carries usable data (not a degradation/error payload)."""
    return result.get("available") is not False and "error" not in result


def _excerpt(tool: str, result: dict[str, Any]) -> str:
    """A short, human-readable summary of a tool result for a citation."""
    if result.get("available") is False:
        return str(result.get("error", "NHTSA data was unavailable."))
    if "error" in result and "recalls" not in result:
        return str(result["error"])

    if tool in ("get_recalls", "check_vin_recalls"):
        count = result.get("count", 0)
        nums = [r.get("NHTSACampaignNumber") for r in result.get("recalls", [])]
        nums = [n for n in nums if n]
        shown = ", ".join(nums[:8]) or "none listed"
        head = ""
        if "vehicle" in result:
            v = result["vehicle"]
            head = (
                f"{v.get('Make', '')} {v.get('Model', '')} "
                f"{v.get('ModelYear', '')}".strip()
                + " — "
            )
        return f"{head}{count} recall campaign(s): {shown}"

    if tool == "decode_vin":
        return (
            f"{result.get('Make', '?')} {result.get('Model', '?')} "
            f"{result.get('ModelYear', '?')}".strip()
        )

    if tool == "get_safety_ratings":
        parts = [
            f"{r.get('VehicleDescription', 'variant')}: "
            f"{r.get('OverallRating', '?')}-star overall"
            for r in result.get("ratings", [])[:4]
        ]
        return "; ".join(parts) or "no NCAP ratings found"

    if tool == "get_complaints":
        total = result.get("total_complaints", 0)
        by_component = result.get("complaints_by_component", {})
        top = next(iter(by_component.items()), None)
        top_str = f"; top component {top[0]} ({top[1]})" if top else ""
        return f"{total} complaint(s){top_str}"

    if tool == "search_eu_recalls":
        count = result.get("count", 0)
        nums = [a.get("caseNumber") for a in result.get("alerts", [])]
        nums = [n for n in nums if n]
        shown = ", ".join(nums[:8]) or "none found"
        return f"EU Safety Gate — {count} motor-vehicle alert(s): {shown}"

    return json.dumps(result, default=str)[:200]


def _extract_citations(answer: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reconcile the markers Claude used in the answer against tools that ran.

    Only markers backed by a real tool call become citations (invented markers
    are dropped); order follows first appearance in the answer.
    """
    by_marker = {r["marker"]: r for r in records}
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for marker in _MARKER_RE.findall(answer):
        if marker in by_marker and marker not in seen:
            seen.add(marker)
            rec = by_marker[marker]
            citations.append(
                {
                    "marker": marker,
                    "tool": rec["tool"],
                    "args": rec["args"],
                    "excerpt": _excerpt(rec["tool"], rec["result"]),
                }
            )
    return citations


def _budget_answer(records: list[dict[str, Any]]) -> str:
    """Truthful answer returned when the cost cap aborts the loop."""
    base = (
        "I stopped this investigation early to stay within the per-request cost "
        "budget, so this answer is incomplete and not a full safety assessment."
    )
    if not records:
        return (
            f"{base} No data was retrieved before the budget was reached — please "
            "retry with a narrower question."
        )
    gathered = "; ".join(
        f"[{r['marker']}] {_excerpt(r['tool'], r['result'])}" for r in records
    )
    return f"{base} Data gathered before stopping: {gathered}."


async def run_agent(
    question: str,
    *,
    settings: Settings,
    client: AsyncAnthropic | None = None,
    logger: Callable[..., None] = log_event,
) -> dict[str, Any]:
    """Run one question through the tool-use loop and return a cited answer.

    Returns ``{"answer", "citations", "tool_calls", "tool_results", "usage"}``.
    ``tool_results`` is the raw payload each tool returned this turn — the
    ground truth for verifying that every fact in the answer (notably recall
    campaign numbers) was actually retrieved, not fabricated. It is provenance
    for callers that grade or audit grounding; ``/ask`` ignores it.
    """
    if client is None:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Adaptive extended thinking, applied to every model call. Thinking blocks
    # are preserved verbatim across rounds (we append the whole response content
    # to the transcript) and ignored when extracting the answer text.
    thinking_kwargs: dict[str, Any] = (
        {"thinking": {"type": "adaptive"}} if settings.extended_thinking else {}
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    records: list[dict[str, Any]] = []  # {marker, tool, args, result}
    slug_counts: dict[str, int] = {}
    in_tokens = 0
    out_tokens = 0
    rounds = 0
    answer: str | None = None
    stop_reason = "unknown"

    def over_budget() -> bool:
        cost = estimate_cost(settings.anthropic_model, in_tokens, out_tokens)
        return cost >= settings.max_cost_usd_per_run

    for _ in range(settings.max_tool_rounds):
        rounds += 1
        resp = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.max_output_tokens,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=registry.TOOL_SCHEMAS,
            **thinking_kwargs,
        )
        in_tokens += resp.usage.input_tokens
        out_tokens += resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})
        stop_reason = resp.stop_reason

        if resp.stop_reason != "tool_use":
            answer = _text_of(resp.content)  # got a final answer — keep it
            break

        # We intend to run tools and loop again: gate on the budget before
        # spending anything more. A real answer above is always kept; only
        # further work is what the cap guards.
        if over_budget():
            stop_reason = "budget_exceeded"
            answer = _budget_answer(records)
            break

        tool_result_blocks: list[dict[str, Any]] = []
        for block in resp.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            marker = _assign_marker(block.name, slug_counts)
            args = dict(block.input)
            try:
                result = await registry.dispatch(block.name, args)
            except Exception as exc:  # unknown tool / handler failure — never crash the loop
                result = {"error": f"{type(exc).__name__}: {exc}"}
            records.append(
                {"marker": marker, "tool": block.name, "args": args, "result": result}
            )
            logger(
                "tool_call",
                tool=block.name,
                marker=marker,
                args=args,
                available=_is_available(result),
            )
            tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"[cite as {marker}]\n{json.dumps(result, default=str)}",
                }
            )
        messages.append({"role": "user", "content": tool_result_blocks})
    else:
        # Ran the full round budget and Claude still wanted tools. Force a final
        # answer with tools withheld — unless we're already over budget.
        if over_budget():
            stop_reason = "budget_exceeded"
            answer = _budget_answer(records)
        else:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You have reached the maximum number of tool calls. Write "
                        "your final answer now using only the information already "
                        "gathered, citing the tool results you used. If key data is "
                        "missing, say so honestly."
                    ),
                }
            )
            rounds += 1
            resp = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=settings.max_output_tokens,
                system=SYSTEM_PROMPT,
                messages=messages,
                **thinking_kwargs,
            )
            in_tokens += resp.usage.input_tokens
            out_tokens += resp.usage.output_tokens
            stop_reason = resp.stop_reason
            answer = _text_of(resp.content)

    answer = answer or ""
    citations = _extract_citations(answer, records)
    tool_calls = [
        {
            "marker": r["marker"],
            "tool": r["tool"],
            "args": r["args"],
            "available": _is_available(r["result"]),
        }
        for r in records
    ]
    return {
        "answer": answer,
        "citations": citations,
        "tool_calls": tool_calls,
        "tool_results": [r["result"] for r in records],
        "usage": {
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "estimated_cost_usd": round(
                estimate_cost(settings.anthropic_model, in_tokens, out_tokens), 6
            ),
            "rounds": rounds,
            "stop_reason": stop_reason,
        },
    }
