"""HTTP routes: ``POST /ask`` (the agent) and ``GET /healthz`` (liveness).

The rate limiter is defined here (so the ``/ask`` decorator can reference it) and
registered onto the app in ``app.py``. Requests are logged as JSON lines at start
and finish; the agent itself logs each tool call.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.agent.loop import run_agent
from app.core.config import get_settings
from app.core.logging import log_event

# Per-IP limiter. The concrete limit string comes from settings and is applied
# on the /ask route below.
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        description="A vehicle-safety question in natural language.",
    )


class AskResponse(BaseModel):
    answer: str
    citations: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    usage: dict[str, Any]


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe. Cheap, unauthenticated, not rate limited."""
    return {"status": "ok"}


@router.post("/ask", response_model=AskResponse)
@limiter.limit(get_settings().rate_limit)
async def ask(request: Request, body: AskRequest) -> AskResponse:
    """Answer one vehicle-safety question with a cited brief."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        # Honest failure for a foreseeable misconfiguration, rather than a 500
        # from the SDK deep in the loop.
        raise HTTPException(
            status_code=503,
            detail="Agent is not configured: ANTHROPIC_API_KEY is not set.",
        )
    log_event(
        "request",
        route="/ask",
        client=get_remote_address(request),
        question=body.question,
    )
    result = await run_agent(body.question, settings=settings)
    log_event(
        "request_done",
        route="/ask",
        citations=len(result["citations"]),
        tool_calls=len(result["tool_calls"]),
        usage=result["usage"],
    )
    return AskResponse(**result)
