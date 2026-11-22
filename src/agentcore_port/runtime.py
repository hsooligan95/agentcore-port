"""The AgentCore Runtime HTTP contract, served locally.

Amazon Bedrock AgentCore Runtime hosts an agent container and talks to
it over HTTP on port 8080 with exactly two mandatory endpoints:

  POST /invocations   the invocation endpoint. Body is app-defined JSON;
                      InvokeAgentRuntime callers conventionally send
                      {"prompt": "..."}. The runtime adds the header
                      X-Amzn-Bedrock-AgentCore-Runtime-Session-Id
                      (session ids are 33-256 characters).
  GET  /ping          health: 200 {"status": "Healthy"} when idle, or
                      {"status": "HealthyBusy"} while work is in flight
                      (busy keeps the session alive).

This module implements that contract with the Python standard library
only, around the unmodified factory-floor-agent. Session handling,
AgentCore Memory, and AgentCore Identity sit behind the interface
shapes in contracts.py (local stubs — no AWS calls anywhere).

The port layer NEVER changes the agent's answer: memory records the
turn after the agent has answered, and identity only scopes who the
turn belongs to. That separation is what the conformance test proves.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agent_loader import load_agent
from .contracts import LocalAgentCoreIdentity, LocalAgentCoreMemory, Principal
from .trace import TraceSink, trace_id_from_headers

SESSION_HEADER = "x-amzn-bedrock-agentcore-runtime-session-id"
SESSION_ID_MIN, SESSION_ID_MAX = 33, 256  # InvokeAgentRuntime constraint
DEFAULT_PORT = 8080  # the AgentCore HTTP contract port


class SessionStore:
    """Runtime sessions: one session id -> its bookkeeping.

    On real AgentCore each session gets its own microVM; locally this
    dict is the stand-in, and the README says so.
    """

    def __init__(self):
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str, principal: Principal) -> tuple[dict, bool]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = {
                    "session_id": session_id,
                    "actor_id": principal.actor_id,
                    "created_at": time.time(),
                    "turns": 0,
                }
                self._sessions[session_id] = session
                return session, True
            return session, False

    def record_turn(self, session_id: str) -> int:
        with self._lock:
            session = self._sessions[session_id]
            session["turns"] += 1
            session["last_seen"] = time.time()
            return session["turns"]


class AgentCoreRuntime:
    """The port: contract + sessions + memory/identity stubs + tracing
    around one agent runner (factory-floor-agent's run_agent)."""

    def __init__(self, run_agent=None, *, memory=None, identity=None,
                 trace_sink: TraceSink | None = None):
        if run_agent is None:
            run_agent = load_agent().run_agent
        self.run_agent = run_agent
        self.memory = memory or LocalAgentCoreMemory()
        self.identity = identity or LocalAgentCoreIdentity()
        self.trace = trace_sink if trace_sink is not None else TraceSink()
        self.sessions = SessionStore()
        self._in_flight = 0
        self._in_flight_lock = threading.Lock()

    # ------------------------------------------------------------ ping
    def ping(self) -> dict:
        with self._in_flight_lock:
            busy = self._in_flight > 0
        return {"status": "HealthyBusy" if busy else "Healthy"}

    # ------------------------------------------------------ invocation
    def invoke(self, body: dict, headers: dict) -> tuple[int, dict, dict]:
        """One /invocations call. Returns (status, response, out_headers)."""
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return 400, {"error": "request body must contain a non-empty "
                                  "'prompt' string"}, {}

        session_id = headers.get(SESSION_HEADER)
        if session_id is not None and not (
                SESSION_ID_MIN <= len(session_id) <= SESSION_ID_MAX):
            return 400, {"error": f"session id must be {SESSION_ID_MIN}-"
                                  f"{SESSION_ID_MAX} characters"}, {}
        if session_id is None:
            session_id = f"local-session-{uuid.uuid4().hex}"  # 46 chars

        principal = self.identity.resolve_principal(headers)
        trace_id, propagated = trace_id_from_headers(headers)
        session, is_new = self.sessions.get_or_create(session_id, principal)
        agent_name = "factory-floor-agent"

        self.trace.emit(trace_id=trace_id, agent=agent_name, type="invocation_received",
                        payload={"session_id": session_id, "actor_id": principal.actor_id,
                                 "session_new": is_new, "trace_propagated": propagated})
        if is_new:
            self.trace.emit(trace_id=trace_id, agent=agent_name, type="session_started",
                            payload={"session_id": session_id,
                                     "actor_id": principal.actor_id})

        with self._in_flight_lock:
            self._in_flight += 1
        try:
            result = self.run_agent(prompt)
        finally:
            with self._in_flight_lock:
                self._in_flight -= 1

        abstained = bool(result.get("abstained") or not result.get("grounded"))
        answer = result.get("answer", "")
        turn = self.sessions.record_turn(session_id)

        # Memory records the turn AFTER the answer exists (port layer
        # bookkeeping; the agent never reads it — see README).
        event = self.memory.create_event(
            actor_id=principal.actor_id, session_id=session_id,
            event_timestamp=time.time(),
            payload=[
                {"conversational": {"role": "USER",
                                    "content": {"text": prompt}}},
                {"conversational": {"role": "ASSISTANT",
                                    "content": {"text": answer}}},
            ])
        self.trace.emit(trace_id=trace_id, agent=agent_name, type="agent_run",
                        payload={"plan": result.get("plan"),
                                 "grounded": bool(result.get("grounded")),
                                 "abstained": abstained,
                                 "attempts": result.get("attempts", 0),
                                 "hits": [{"doc_id": h.chunk.doc_id,
                                           "source": h.chunk.source}
                                          for h in result.get("hits", [])]})
        self.trace.emit(trace_id=trace_id, agent=agent_name, type="invocation_completed",
                        payload={"session_id": session_id, "turn": turn,
                                 "memory_event_id": event.event_id,
                                 "outcome": "abstained" if abstained else "answered"})

        response = {
            "answer": answer,
            "grounded": bool(result.get("grounded")),
            "abstained": abstained,
            "plan": result.get("plan"),
            "session_id": session_id,
            "actor_id": principal.actor_id,
            "session_turn": turn,
            "trace_id": trace_id,
        }
        return 200, response, {SESSION_HEADER: session_id}


def make_server(runtime: AgentCoreRuntime, host: str = "0.0.0.0",
                port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _headers_dict(self) -> dict:
            return {k.lower(): v for k, v in self.headers.items()}

        def _send_json(self, status: int, payload: dict, extra: dict | None = None):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/ping":
                self._send_json(200, runtime.ping())
            else:
                self._send_json(404, {"error": f"no such path: {self.path}"})

        def do_POST(self):
            if self.path != "/invocations":
                self._send_json(404, {"error": f"no such path: {self.path}"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json(400, {"error": f"invalid JSON body: {exc}"})
                return
            status, response, out_headers = runtime.invoke(body, self._headers_dict())
            self._send_json(status, response, out_headers)

        def log_message(self, *args):  # keep test/CI output clean
            pass

    return ThreadingHTTPServer((host, port), Handler)
