"""Schema-shape tests.

Two contracts are asserted here, both structural (no network, no SDK):

1. Every schema is a well-formed Anthropic tool definition — the shape the
   Messages API ``tools`` array requires: a name matching Anthropic's allowed
   pattern, a non-empty description, and an object-typed ``input_schema`` whose
   ``required`` list references only declared properties.
2. Every schema agrees with the real signature of the handler it will be
   dispatched to — no invented parameters, and the mandatory arguments line up
   with ``required`` — so a valid model tool call can never miss a required arg.
"""

import inspect
import re

import pytest

from app.tools import registry
from app.tools.schemas import SCHEMAS

# name -> handler, resolved the same way the loop dispatches — source-agnostic,
# so NHTSA and EU Safety Gate handlers are both covered without this test knowing
# which module each lives in.
_HANDLERS = {tool.schema["name"]: tool.handler for tool in registry.TOOLS}

# Anthropic tool names: 1-64 chars from [a-zA-Z0-9_-].
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_JSON_SCHEMA_TYPES = {
    "object",
    "array",
    "string",
    "integer",
    "number",
    "boolean",
    "null",
}


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda s: s["name"])
def test_schema_has_anthropic_tool_shape(schema):
    assert isinstance(schema["name"], str)
    assert _NAME_RE.match(schema["name"]), schema["name"]

    assert isinstance(schema["description"], str)
    assert schema["description"].strip(), "description must be non-empty"

    input_schema = schema["input_schema"]
    assert input_schema["type"] == "object"

    props = input_schema["properties"]
    assert isinstance(props, dict) and props, "at least one property expected"
    for pname, pschema in props.items():
        assert pschema.get("type") in _JSON_SCHEMA_TYPES, (pname, pschema.get("type"))
        assert pschema.get("description", "").strip(), f"{pname} needs a description"

    required = input_schema.get("required", [])
    assert isinstance(required, list)
    assert all(isinstance(r, str) for r in required)
    # required may only name declared properties.
    assert set(required) <= set(props), set(required) - set(props)


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda s: s["name"])
def test_schema_matches_handler_signature(schema):
    handler = _HANDLERS[schema["name"]]
    params = inspect.signature(handler).parameters

    declared = set(schema["input_schema"]["properties"])
    required = set(schema["input_schema"].get("required", []))

    # No invented parameters: everything declared is a real handler argument.
    assert declared <= set(params), declared - set(params)

    # Mandatory args (no default) must be declared AND marked required, and
    # nothing optional may sneak into required.
    mandatory = {
        name
        for name, p in params.items()
        if p.default is inspect.Parameter.empty
        and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    }
    assert mandatory <= declared, mandatory - declared
    assert mandatory == required, (mandatory, required)


def test_every_registered_tool_has_exactly_one_schema():
    registered = [t.schema["name"] for t in registry.TOOLS]
    schema_names = [s["name"] for s in SCHEMAS]
    assert registered == schema_names
    assert len(schema_names) == len(set(schema_names))
