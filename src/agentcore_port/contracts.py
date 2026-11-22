"""AgentCore Memory and Identity — interface shapes with local stubs.

These classes mirror the *shapes* of the Amazon Bedrock AgentCore
Memory and Identity APIs closely enough that swapping the stub for a
boto3-backed implementation touches only this file:

AgentCore Memory (control/data plane concepts):
  - an event is (actorId, sessionId, eventTimestamp, payload), where a
    conversational payload is a list of {conversational: {role, content}}
  - ListEvents(actorId, sessionId) returns events in timestamp order
  - RetrieveMemoryRecords(memoryId, namespace, searchQuery) is the
    semantic-strategy lookup; the stub does substring ranking and says so

AgentCore Identity:
  - a workload identity has a name; callers exchange it for a short-lived
    OAuth2 access token (GetResourceOauth2Token / workload access token)
  - the stub mints an UNSIGNED, clearly-local token. It is not a
    credential and would be rejected by anything real — by design.

LOCAL STUBS. Nothing here talks to AWS.
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass, field


# ------------------------------------------------------------------ memory

@dataclass
class MemoryEvent:
    event_id: str
    actor_id: str
    session_id: str
    event_timestamp: float
    payload: list[dict]


class LocalAgentCoreMemory:
    """In-memory stub behind the AgentCore Memory interface shape."""

    def __init__(self, memory_id: str = "local-memory-stub"):
        self.memory_id = memory_id
        self._events: list[MemoryEvent] = []

    def create_event(self, *, actor_id: str, session_id: str,
                     event_timestamp: float, payload: list[dict]) -> MemoryEvent:
        """Shape of AgentCore Memory CreateEvent."""
        event = MemoryEvent(
            event_id=f"local-{uuid.uuid4().hex[:16]}",
            actor_id=actor_id, session_id=session_id,
            event_timestamp=event_timestamp, payload=payload,
        )
        self._events.append(event)
        return event

    def list_events(self, *, actor_id: str, session_id: str,
                    max_results: int = 100) -> list[MemoryEvent]:
        """Shape of AgentCore Memory ListEvents (timestamp order)."""
        found = [e for e in self._events
                 if e.actor_id == actor_id and e.session_id == session_id]
        return sorted(found, key=lambda e: e.event_timestamp)[:max_results]

    def retrieve_memory_records(self, *, namespace: str, search_query: str,
                                max_results: int = 10) -> list[dict]:
        """Shape of RetrieveMemoryRecords. STUB ranking: substring match
        over event text — real AgentCore uses semantic strategies."""
        needle = search_query.lower()
        records = []
        for event in self._events:
            text = json.dumps(event.payload)
            if needle in text.lower():
                records.append({
                    "memoryRecordId": event.event_id,
                    "namespace": namespace,
                    "content": {"text": text},
                    "score": None,  # stub does not compute a semantic score
                })
        return records[:max_results]


# ---------------------------------------------------------------- identity

@dataclass
class Principal:
    """Who is calling, as resolved through the Identity-shaped stub."""
    actor_id: str
    workload_name: str
    authenticated: bool
    claims: dict = field(default_factory=dict)


class LocalAgentCoreIdentity:
    """Stub behind the AgentCore Identity shape.

    ``get_workload_access_token`` mirrors the workload-token exchange:
    a workload name in, a short-lived bearer token out. The token is an
    unsigned JWT-shaped string marked ``alg: none`` / ``iss: local-stub``
    so it can never be mistaken for a real credential.
    """

    def __init__(self, workload_name: str = "factory-floor-qa-agent"):
        self.workload_name = workload_name

    def get_workload_access_token(self, *, workload_name: str | None = None,
                                  ttl_seconds: int = 300) -> dict:
        now = int(time.time())
        header = {"alg": "none", "typ": "JWT"}
        claims = {
            "iss": "local-stub-agentcore-identity",
            "sub": workload_name or self.workload_name,
            "iat": now, "exp": now + ttl_seconds,
            "local_stub": True,
        }
        enc = lambda d: base64.urlsafe_b64encode(  # noqa: E731
            json.dumps(d).encode()).rstrip(b"=").decode()
        token = f"{enc(header)}.{enc(claims)}."
        return {"accessToken": token, "expiresIn": ttl_seconds,
                "tokenType": "Bearer"}

    def resolve_principal(self, headers: dict) -> Principal:
        """Propagate caller identity from the invocation headers.

        Precedence: an explicit actor header (the local stand-in for a
        validated token subject), else the bearer token's ``sub`` claim,
        else the default workload identity (unauthenticated local call).
        """
        actor = headers.get("x-agentcore-actor-id")
        if actor:
            return Principal(actor_id=actor, workload_name=self.workload_name,
                             authenticated=True, claims={"via": "actor-header"})
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
            try:
                payload_b64 = token.split(".")[1]
                payload_b64 += "=" * (-len(payload_b64) % 4)
                claims = json.loads(base64.urlsafe_b64decode(payload_b64))
                sub = claims.get("sub")
                if sub:
                    return Principal(actor_id=str(sub),
                                     workload_name=self.workload_name,
                                     authenticated=True, claims=claims)
            except Exception:
                pass  # opaque token: fall through to the default principal
            return Principal(actor_id="bearer-caller",
                             workload_name=self.workload_name,
                             authenticated=True, claims={"via": "opaque-bearer"})
        return Principal(actor_id="local-anonymous",
                         workload_name=self.workload_name,
                         authenticated=False, claims={})
