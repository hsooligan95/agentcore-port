# AgentCorePort — one agent, two paths, identical answers

The AWS Bedrock AgentCore deployment pattern, implemented so it runs
**locally with no AWS account**: [factory-floor-agent](../factory-floor-agent)'s
LangGraph QA agent, packaged behind the AgentCore Runtime contract —
the HTTP invocation interface AgentCore expects — with Memory and
Identity behind their AgentCore interface shapes.

> **Honesty box — read this first.**
> **Local conformance is proven** (below): the same agent code runs
> in-process and served through the AgentCore-shaped runtime, and the
> two paths answer identically on all 18 labeled eval cases.
> **Cloud deploy is NOT done and is not claimed.** The templates in
> `infra/` are untested against AWS; deploying them requires an AWS
> sandbox account. Memory and Identity here are local stubs behind the
> real API shapes — they make no AWS calls.

## The demo (30 seconds)

```
$ python serve.py --port 8080
AgentCore Runtime contract on 0.0.0.0:8080 (/invocations, /ping) — local harness, no AWS calls

$ curl -s localhost:8080/ping
{"status": "Healthy"}

$ curl -s -X POST localhost:8080/invocations \
    -H 'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: readme-demo-session-0123456789abcdef' \
    -H 'X-Amzn-Bedrock-AgentCore-Runtime-Custom-Trace-Id: trace-readme-demo' \
    -d '{"prompt":"What does checkpointing enable in LangGraph?"}'
{"answer": "Checkpointing enables several capabilities.", "grounded": true,
 "abstained": false, "plan": "concept lookup", "session_turn": 1,
 "actor_id": "local-anonymous", "trace_id": "trace-readme-demo", ...}

$ curl -s -X POST localhost:8080/invocations \   # same session, turn 2
    -H 'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: readme-demo-session-0123456789abcdef' \
    -d '{"prompt":"What is the best recipe for banana bread?"}'
{"answer": "I could not ground an answer to that question in the
 document set, so I am abstaining rather than guessing.",
 "grounded": false, "abstained": true, "session_turn": 2, ...}
```

(Captured verbatim from a local run; the full trace the served path
emitted for these two calls is in `conformance/results/sample-trace.jsonl`.)

## The contract implemented

AgentCore Runtime's HTTP protocol contract, from the AWS docs:

- `POST /invocations` on port **8080** — body is app-defined JSON;
  InvokeAgentRuntime callers conventionally send `{"prompt": "..."}`.
- `GET /ping` → `{"status": "Healthy"}` when idle,
  `{"status": "HealthyBusy"}` while an invocation is in flight.
- Session routing via `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`;
  session ids are validated at 33–256 characters (the
  InvokeAgentRuntime constraint), minted locally when absent, and
  echoed back on the response.
- Custom headers (`X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`) are the
  pass-through channel — the port reads the trace ID from one.

## Conformance — the point of the repo

```
$ python conformance/run_conformance.py
cases: 18  identical: 18  divergences: none
scored pass — in-process: 18/18  served: 18/18
AgentTrace events emitted by the served path: 72 (trace trace-conformance-agentcore-port)
CONFORMANCE: PASS
```

Every case from rag-evaluation-harness's labeled set
(`conformance/cases.jsonl`, copied verbatim) runs through the agent
twice — in-process, and over HTTP through the runtime harness — and the
paths must agree **exactly** on answer text, plan, grounded/abstained
outcome, and retrieved doc ids, and both are scored with the harness's
rules. Full per-case results: `conformance/results/conformance.json`.
Both paths force the agent's deterministic offline composer (provider
env vars cleared): comparing a live model against itself would measure
the model, not the port.

## How the pieces map

| AgentCore component | Here | Real or stub? |
|---|---|---|
| Runtime contract (`/invocations`, `/ping`, sessions) | `src/agentcore_port/runtime.py`, stdlib HTTP server | **Real** — the contract behaviour itself, served locally |
| The agent | factory-floor-agent, loaded unmodified (`agent_loader.py`) | **Real** — same module both paths |
| Memory | `contracts.LocalAgentCoreMemory` — CreateEvent / ListEvents / RetrieveMemoryRecords shapes | Stub: in-memory store, substring retrieval (real Memory uses semantic strategies) |
| Identity | `contracts.LocalAgentCoreIdentity` — workload token exchange shape, principal resolution from headers | Stub: mints an unsigned, `local_stub`-marked token; never a real credential |
| Gateway | — | Not in this port. agent-gate's policy model is the local analogue; see MIGRATION.md |
| Deployment | `infra/` (Dockerfile, CloudFormation, execution-role policy, CreateAgentRuntime request) | **Untested against AWS** — reviewable artifacts, not a deployment |

Memory records each turn **after** the agent answers, and Identity only
scopes who the turn belongs to — the port layer never feeds the agent's
composition. That separation is deliberate, and it is what makes the
conformance claim meaningful.

## AgentTrace

The served path emits AgentTrace schema v1 events (source
`agentcore-port`, agent `factory-floor-agent`) under a propagated trace
ID — from the `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Trace-Id` or
`X-Agenttrace-Trace-Id` header, or `AGENTTRACE_TRACE_ID` — following the
fleet's emit-side pattern: `invocation_received`, `session_started`,
`agent_run` (the groundedness verdict and retrieved doc ids, as data),
`invocation_completed`. Point `serve.py`'s `AGENTCORE_PORT_TRACE_OUT`
at a file and agent-trace ingests the run like any other producer's.

## Run it

```
# sibling layout: this repo next to factory-floor-agent
# (or set FACTORY_FLOOR_AGENT_HOME to its checkout)
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python serve.py                 # the contract, on :8080
.venv/bin/python -m pytest tests/         # 12 tests
.venv/bin/python conformance/run_conformance.py
```

## Limitations

- **No live AWS deployment exists.** Nothing in `infra/` has been
  applied, built for ARM64, or invoked through the real
  `InvokeAgentRuntime` API. The one-command deploy story is documented,
  not demonstrated.
- **Memory/Identity are stubs.** Shapes are faithful; semantics are
  local (in-memory events, substring retrieval, unsigned tokens).
  Swapping in boto3 touches only `contracts.py` — that is the design —
  but it has not been done or tested against the real services.
- **Sessions are a dict, not microVMs.** Real AgentCore isolates each
  session in its own microVM; locally, sessions share one process.
- **One agent, one protocol.** The HTTP protocol contract only — no
  MCP/A2A protocol variants, no Gateway, no streaming (SSE) responses.
- **The agent is unchanged, including its limits** — offline extractive
  composition, abstains outside its document set. The port proves the
  deployment shape, not new agent capability.

## Layout

```
serve.py                  entry point: the contract server
src/agentcore_port/
  agent_loader.py         locates + imports factory-floor-agent, unmodified
  runtime.py              /invocations + /ping, sessions, in-flight ping state
  contracts.py            Memory + Identity interface shapes (local stubs)
  trace.py                AgentTrace schema v1 emission, trace-ID propagation
conformance/              two-path conformance runner + labeled cases + results
infra/                    UNTESTED deployment artifacts (see honesty box)
tests/                    contract tests + conformance subset test
MIGRATION.md              Lambda/Fargate -> AgentCore: what changes, what doesn't
```
