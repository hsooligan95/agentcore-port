"""Contract tests for the local AgentCore Runtime harness.

Run: python -m pytest tests/   (with factory-floor-agent's venv or any
env that has langgraph installed; the agent is loaded unmodified)
"""
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentcore_port.contracts import (  # noqa: E402
    LocalAgentCoreIdentity, LocalAgentCoreMemory)
from agentcore_port.runtime import (  # noqa: E402
    SESSION_HEADER, AgentCoreRuntime, make_server)
from agentcore_port.trace import TraceSink  # noqa: E402

SESSION = "test-session-0123456789abcdef0123456789"  # 41 chars
Q = "What is a state graph in LangGraph and how does state flow through it?"


@pytest.fixture(scope="module")
def server():
    sink = TraceSink()
    runtime = AgentCoreRuntime(trace_sink=sink)
    srv = make_server(runtime, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, runtime, sink
    srv.shutdown()


def _call(server, method, path, body=None, headers=None):
    port = server.server_address[1]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode()), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode()), e.headers


def test_ping_healthy(server):
    srv, _, _ = server
    status, body, _ = _call(srv, "GET", "/ping")
    assert status == 200
    assert body == {"status": "Healthy"}


def test_ping_busy_while_in_flight(server):
    _, runtime, _ = server
    with runtime._in_flight_lock:
        runtime._in_flight += 1
    try:
        assert runtime.ping() == {"status": "HealthyBusy"}
    finally:
        with runtime._in_flight_lock:
            runtime._in_flight -= 1
    assert runtime.ping() == {"status": "Healthy"}


def test_invocation_answers_and_echoes_session(server):
    srv, _, _ = server
    status, body, headers = _call(srv, "POST", "/invocations",
                                  {"prompt": Q}, {SESSION_HEADER: SESSION})
    assert status == 200
    assert body["grounded"] is True and body["abstained"] is False
    assert "state" in body["answer"].lower()
    assert body["session_id"] == SESSION
    assert headers.get(SESSION_HEADER) == SESSION
    assert body["session_turn"] >= 1


def test_invocation_requires_prompt(server):
    srv, _, _ = server
    status, body, _ = _call(srv, "POST", "/invocations", {"nope": 1})
    assert status == 400 and "prompt" in body["error"]


def test_session_id_length_validated(server):
    srv, _, _ = server
    status, body, _ = _call(srv, "POST", "/invocations", {"prompt": Q},
                            {SESSION_HEADER: "too-short"})
    assert status == 400 and "33" in body["error"]


def test_session_minted_when_absent(server):
    srv, _, _ = server
    status, body, headers = _call(srv, "POST", "/invocations", {"prompt": Q})
    assert status == 200
    assert 33 <= len(body["session_id"]) <= 256
    assert headers.get(SESSION_HEADER) == body["session_id"]


def test_unknown_path_404(server):
    srv, _, _ = server
    status, _, _ = _call(srv, "GET", "/nope")
    assert status == 404


def test_memory_records_turns_per_session(server):
    srv, runtime, _ = server
    session = "memory-session-0123456789abcdef012345"
    _call(srv, "POST", "/invocations", {"prompt": Q}, {SESSION_HEADER: session})
    events = runtime.memory.list_events(actor_id="local-anonymous",
                                        session_id=session)
    assert len(events) == 1
    roles = [p["conversational"]["role"] for p in events[0].payload]
    assert roles == ["USER", "ASSISTANT"]
    records = runtime.memory.retrieve_memory_records(
        namespace="test", search_query="state graph")
    assert records and events[0].event_id in {
        r["memoryRecordId"] for r in records}


def test_identity_propagation(server):
    srv, runtime, _ = server
    session = "identity-session-0123456789abcdef0123"
    status, body, _ = _call(srv, "POST", "/invocations", {"prompt": Q},
                            {SESSION_HEADER: session,
                             "X-Agentcore-Actor-Id": "recruiter-demo"})
    assert status == 200 and body["actor_id"] == "recruiter-demo"
    events = runtime.memory.list_events(actor_id="recruiter-demo",
                                        session_id=session)
    assert len(events) == 1


def test_identity_stub_token_is_marked_local():
    identity = LocalAgentCoreIdentity()
    token = identity.get_workload_access_token()
    assert token["tokenType"] == "Bearer" and token["expiresIn"] == 300
    principal = identity.resolve_principal(
        {"authorization": f"Bearer {token['accessToken']}"})
    assert principal.actor_id == "factory-floor-qa-agent"
    assert principal.claims["local_stub"] is True


def test_trace_events_schema_v1_and_propagated(server):
    srv, _, sink = server
    session = "trace-session-0123456789abcdef0123456"
    trace = "trace-test-propagated-123"
    _call(srv, "POST", "/invocations", {"prompt": Q},
          {SESSION_HEADER: session, "X-Agenttrace-Trace-Id": trace})
    mine = [e for e in sink.events if e["trace_id"] == trace]
    types = [e["type"] for e in mine]
    assert types == ["invocation_received", "session_started",
                     "agent_run", "invocation_completed"]
    for e in mine:
        assert e["schema_version"] == "1" and e["kind"] == "event"
        assert e["source"] == "agentcore-port"
        assert e["agent"] == "factory-floor-agent"
    assert mine[0]["payload"]["trace_propagated"] is True
    assert mine[2]["payload"]["grounded"] is True
