# Copilot instructions — agentcore-port

You are working in **AgentCorePort**: the AWS Bedrock AgentCore
deployment pattern, implemented to run locally with no AWS account.
factory-floor-agent's LangGraph QA agent is packaged behind the
AgentCore Runtime HTTP contract, with Memory and Identity behind their
AgentCore interface shapes.

## Stack

- Python 3, standard-library HTTP server. Entry: `serve.py` (port 8080,
  `POST /invocations`, `GET /ping`).
- `src/` holds the runtime harness and `contracts.py` (Memory/Identity
  stubs); deployment templates live in `infra/`; the two-path
  conformance run lives in `conformance/`.

## Tests

```bash
.venv/bin/python -m pytest tests/   # 12 tests
```

## Architecture notes

- The agent under test is loaded UNMODIFIED from factory-floor-agent
  (sibling checkout or `FACTORY_FLOOR_AGENT_HOME`). Never copy or fork
  its code into this repo — the port is the deliverable, not the agent.
- Conformance is the claim: in-process and served paths must answer
  identically on all 18 labeled eval cases (answer, plan,
  grounded/abstained, retrieved doc IDs). A divergence is a bug in the
  port, not in the agent.
- Runtime contract details are load-bearing: session header
  `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` validated at 33-256
  chars, minted when absent, echoed on responses; ping reports
  Healthy / HealthyBusy (busy while an invocation is in flight).
- Memory records turns AFTER the agent answers and never feeds
  composition — that separation is what keeps the conformance claim
  meaningful. Identity tokens are unsigned and `local_stub`-marked,
  never mistakable for real credentials.
- Everything in `infra/` is UNTESTED against AWS. Local conformance is
  proven; a cloud deploy requires an AWS sandbox account and is never
  to be described as done.

## Shared rules

- Use Unix LF line endings in every file; never CRLF.
- Never commit secrets, tokens, or credentials — real or synthetic-looking.
- Tests must pass before you describe a change as complete; run the test
  command above and report honestly if you cannot.
- Prefer the smallest complete implementation: reuse what already exists in
  this repo before adding new code, files, or dependencies.
