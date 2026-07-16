"""Anthropic tool-use JSON schemas for the NHTSA tools.

These are the definitions passed in the Messages API ``tools`` array. Claude
sees only the ``name``, ``description``, and ``input_schema`` below — nothing
about how the tools are implemented — so every description is written to be
self-contained for a reader with zero prior context: what the tool returns,
when to reach for it, and what each parameter means.

Parameter notes:
- NHTSA does not publish closed value lists for make/model, so those are free
  strings (case-insensitive on the API) rather than enums. There are no genuine
  enum parameters across these five tools; ``model_year`` is bounded by a
  ``minimum``/``maximum`` instead.
- ``model_year`` is a four-digit integer. The bounds only reject nonsense; a
  plausible-but-unreleased future year is a matter of judgement for the agent,
  not something the schema hard-blocks.

Keep these in sync with the handler signatures in ``nhtsa.py`` — the schema
tests assert that every declared property is a real parameter and that every
required property is a parameter with no default.
"""

from __future__ import annotations

from typing import Any

_MIN_YEAR = 1950
_MAX_YEAR = 2100

_MAKE = {
    "type": "string",
    "description": (
        "Vehicle manufacturer or brand, e.g. 'Honda', 'Ford', 'Tesla'. "
        "Case-insensitive; spelling must match the marque, not a sub-brand."
    ),
}
_MODEL = {
    "type": "string",
    "description": (
        "Vehicle model name, e.g. 'Civic', 'F-150', 'Model 3'. Case-insensitive. "
        "Use the model only — do not append the trim or body style."
    ),
}
_MODEL_YEAR = {
    "type": "integer",
    "description": "Four-digit model year of the vehicle, e.g. 2020.",
    "minimum": _MIN_YEAR,
    "maximum": _MAX_YEAR,
}


DECODE_VIN: dict[str, Any] = {
    "name": "decode_vin",
    "description": (
        "Decode a Vehicle Identification Number (VIN) into the vehicle's "
        "attributes: make, model, model year, trim, body class, engine, "
        "drivetrain, and factory safety equipment. A VIN is the 17-character "
        "alphanumeric code stamped on a vehicle (also printed on its "
        "registration and insurance card); partial VINs are accepted but return "
        "fewer fields. Use this when the user gives a VIN and wants to know what "
        "vehicle it identifies. Covers US-market vehicles only (source: NHTSA "
        "vPIC)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "vin": {
                "type": "string",
                "description": (
                    "The VIN to decode, e.g. '1HGCM82633A004352'. Provide the "
                    "raw code with no spaces or dashes. 17 characters for a full "
                    "VIN; a shorter partial VIN is allowed."
                ),
            },
            "model_year": {
                "type": "integer",
                "description": (
                    "The vehicle's model year, e.g. 2020. Optional, but supplying "
                    "it improves accuracy for VINs from 2009 or earlier, where "
                    "the year character is ambiguous."
                ),
                "minimum": _MIN_YEAR,
                "maximum": _MAX_YEAR,
            },
        },
        "required": ["vin"],
    },
}


CHECK_VIN_RECALLS: dict[str, Any] = {
    "name": "check_vin_recalls",
    "description": (
        "Given a single VIN, decode it and look up the safety-recall campaigns "
        "for that exact vehicle in one step. Use this for the common question "
        "'does the car with this VIN have any recalls?' — it saves calling "
        "decode_vin and get_recalls separately. Returns the decoded vehicle plus "
        "its recall campaigns (count and per-campaign details). Covers US-market "
        "vehicles only (source: NHTSA)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "vin": {
                "type": "string",
                "description": (
                    "The 17-character VIN to check, e.g. '5UXWX7C5XBA000000'. "
                    "Provide the raw code with no spaces or dashes."
                ),
            },
        },
        "required": ["vin"],
    },
}


GET_RECALLS: dict[str, Any] = {
    "name": "get_recalls",
    "description": (
        "Look up NHTSA safety-recall campaigns for a vehicle identified by make, "
        "model, and model year. Returns a total count and a list of campaigns; "
        "each campaign includes its official NHTSA campaign number (e.g. "
        "'21V215000'), the affected component, a summary of the defect, its "
        "safety consequence, and the manufacturer's remedy. Use this when the "
        "user asks whether a specific vehicle has recalls, what a recall covers, "
        "or how a defect is fixed. Covers US-market vehicles only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "make": _MAKE,
            "model": _MODEL,
            "model_year": _MODEL_YEAR,
        },
        "required": ["make", "model", "model_year"],
    },
}


GET_SAFETY_RATINGS: dict[str, Any] = {
    "name": "get_safety_ratings",
    "description": (
        "Get NHTSA New Car Assessment Program (NCAP) crash-test star ratings for "
        "a vehicle identified by make, model, and model year. Returns ratings per "
        "body-style variant: overall, frontal-crash, side-crash, and rollover, "
        "each on a 1-to-5-star scale, along with noted advanced safety features. "
        "Use this when the user asks how safe a vehicle is, how it scored in "
        "crash tests, or wants to compare crash performance between vehicles. "
        "Ratings exist only for vehicles NHTSA has tested — some make/model/years "
        "return none. Covers US-market vehicles only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "make": _MAKE,
            "model": _MODEL,
            "model_year": _MODEL_YEAR,
        },
        "required": ["make", "model", "model_year"],
    },
}


GET_COMPLAINTS: dict[str, Any] = {
    "name": "get_complaints",
    "description": (
        "Get consumer complaints filed with NHTSA for a vehicle identified by "
        "make, model, and model year. Returns the total complaint count, a "
        "breakdown of how many complaints fall under each vehicle component "
        "(e.g. ENGINE, STEERING, ELECTRICAL), and the most recent complaint "
        "narratives. Use this when the user asks about known problems, "
        "reliability, or owner-reported defects; the component with the most "
        "complaints is the most-reported problem area. Covers US-market vehicles "
        "only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "make": _MAKE,
            "model": _MODEL,
            "model_year": _MODEL_YEAR,
            "limit": {
                "type": "integer",
                "description": (
                    "How many of the most recent complaint narratives to return. "
                    "Optional; defaults to 10. The component breakdown always "
                    "covers all complaints regardless of this value."
                ),
                "minimum": 1,
                "maximum": 50,
            },
        },
        "required": ["make", "model", "model_year"],
    },
}


# Order mirrors the registry and the tool set exposed by the MCP server.
SCHEMAS: list[dict[str, Any]] = [
    DECODE_VIN,
    CHECK_VIN_RECALLS,
    GET_RECALLS,
    GET_SAFETY_RATINGS,
    GET_COMPLAINTS,
]
