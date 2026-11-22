---
mode: agent
description: Review the current diff against agentcore-port's invariants
---

Review my current diff against this repo's invariants:

- The agent is loaded UNMODIFIED from factory-floor-agent; never copy or fork its code into this repo.
- In-process and served paths must answer identically on all 18 conformance cases; a divergence is a bug in the port, not the agent.
- The session header X-Amzn-Bedrock-AgentCore-Runtime-Session-Id is validated at 33-256 chars, minted when absent, and echoed on responses.
- Memory records turns AFTER the agent answers and never feeds composition; everything in infra/ is UNTESTED against AWS.

Flag every violation with file and line. Also flag any change that
alters a documented behavior contract (output shapes, exit codes,
event schemas, recorded artifacts) without updating the docs and
tests that describe it. No style nitpicks — correctness and contract
violations only.
