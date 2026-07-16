"""Tool registry: the single source of truth binding each tool's Anthropic
schema to the async callable that executes it.

The agent loop stays deliberately generic. It reads:
  - ``TOOL_SCHEMAS`` — the list to advertise to Claude in the ``tools`` array;
  - ``dispatch(name, arguments)`` — to run whichever tool Claude picked.

Neither the loop nor this module knows anything NHTSA-specific. When the EU
tools (RAPEX/KBA, NCAP RAG) arrive, they append to ``TOOLS`` and everything
downstream keeps working unchanged.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from . import nhtsa, schemas

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    """One tool: its Anthropic schema paired with the callable that runs it."""

    schema: dict[str, Any]
    handler: ToolHandler

    @property
    def name(self) -> str:
        return self.schema["name"]


# The registry. Each entry pairs a schema (what Claude sees) with the handler
# (what actually runs). Adding a tool is a one-line append here.
TOOLS: list[Tool] = [
    Tool(schemas.DECODE_VIN, nhtsa.decode_vin),
    Tool(schemas.CHECK_VIN_RECALLS, nhtsa.check_vin_recalls),
    Tool(schemas.GET_RECALLS, nhtsa.get_recalls),
    Tool(schemas.GET_SAFETY_RATINGS, nhtsa.get_safety_ratings),
    Tool(schemas.GET_COMPLAINTS, nhtsa.get_complaints),
]

# Derived views, computed once. TOOL_SCHEMAS is the array handed to the API;
# _HANDLERS is the name -> callable map used to dispatch a tool_use block.
TOOL_SCHEMAS: list[dict[str, Any]] = [tool.schema for tool in TOOLS]
_HANDLERS: dict[str, ToolHandler] = {tool.name: tool.handler for tool in TOOLS}


def tool_names() -> list[str]:
    """The names of every registered tool, in registration order."""
    return [tool.name for tool in TOOLS]


async def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute the registered tool ``name`` with keyword ``arguments``.

    Raises ``KeyError`` for an unregistered tool so the caller can surface a
    clear error to the model instead of silently doing nothing.
    """
    try:
        handler = _HANDLERS[name]
    except KeyError:
        raise KeyError(
            f"Unknown tool {name!r}. Registered tools: {tool_names()}"
        ) from None
    return await handler(**arguments)
