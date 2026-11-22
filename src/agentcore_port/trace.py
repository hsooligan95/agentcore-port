"""AgentTrace schema v1 emission from the served path.

Same pattern factory-floor-agent established (see its trace_emit.py):
emission is configured by the environment, reshaped only from computed
state, and never feeds back into the agent. Events conform to the
AgentTrace event schema v1 (agent-trace/agenttrace/schema.py): every
event carries schema_version "1", trace_id, ts, source, agent, type,
kind, payload.

The trace ID is propagated, not minted, when the caller supplies one —
via the AgentCore custom header
``X-Amzn-Bedrock-AgentCore-Runtime-Custom-Trace-Id`` (custom headers are
the headers AgentCore passes through to the runtime), the plain
``X-Agenttrace-Trace-Id`` header, or the ``AGENTTRACE_TRACE_ID``
environment fallback (the fleet-wide pattern). With none of those, a
local trace ID is minted so the served path is always auditable.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

SOURCE = "agentcore-port"
SCHEMA_VERSION = "1"
CORE_FIELDS = {  # mirrors agent-trace agenttrace/schema.py CORE_FIELDS
    "schema_version": str, "trace_id": str, "ts": str, "source": str,
    "agent": str, "type": str, "kind": str, "payload": dict,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def trace_id_from_headers(headers: dict, env: dict | None = None) -> tuple[str, bool]:
    """Resolve (trace_id, propagated?) from headers / environment."""
    env = os.environ if env is None else env
    for header in ("x-amzn-bedrock-agentcore-runtime-custom-trace-id",
                   "x-agenttrace-trace-id"):
        value = headers.get(header)
        if value:
            return value, True
    if env.get("AGENTTRACE_TRACE_ID"):
        return env["AGENTTRACE_TRACE_ID"], True
    return f"trace-local-{uuid.uuid4().hex[:12]}", False


class TraceSink:
    """Append schema-v1 events as JSONL to a file (or keep in memory)."""

    def __init__(self, out: str | Path | None = None):
        self.out = Path(out) if out else None
        self.events: list[dict] = []

    def emit(self, *, trace_id: str, agent: str, type: str, payload: dict,
             kind: str = "event") -> dict:
        event = {
            "schema_version": SCHEMA_VERSION,
            "trace_id": trace_id,
            "ts": _now(),
            "source": SOURCE,
            "agent": agent,
            "type": type,
            "kind": kind,
            "payload": payload,
        }
        for name, typ in CORE_FIELDS.items():  # fail loudly, like the store
            if name not in event or not isinstance(event[name], typ):
                raise ValueError(f"trace event field {name!r} nonconformant")
        self.events.append(event)
        if self.out is not None:
            with self.out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
        return event
