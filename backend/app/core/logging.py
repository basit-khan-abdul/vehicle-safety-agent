"""Structured JSON-lines logging to stdout.

One JSON object per line so logs stay both human-skimmable and machine-parseable
(pipe to ``jq``, ship to any collector) without pulling in a logging framework.
Used for request start/end and every tool call. Never log secrets.
"""

from __future__ import annotations

import datetime
import json
import sys
from typing import Any


def log_event(event: str, **fields: Any) -> None:
    """Emit one structured log line: ``{"ts", "event", **fields}``."""
    record = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    print(json.dumps(record, default=str), file=sys.stdout, flush=True)
