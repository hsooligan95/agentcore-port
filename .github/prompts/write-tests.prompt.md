---
mode: agent
description: Write tests for a named module in agentcore-port
---

Write tests for the module I name, following this repo's existing test
style, layout, and fixtures. Cover the behavior the module documents,
including these invariants where they apply:

- The agent is loaded UNMODIFIED from factory-floor-agent; never copy or fork its code into this repo.
- In-process and served paths must answer identically on all 18 conformance cases; a divergence is a bug in the port, not the agent.
- The session header X-Amzn-Bedrock-AgentCore-Runtime-Session-Id is validated at 33-256 chars, minted when absent, and echoed on responses.

Then run the test suite:

    .venv/bin/python -m pytest tests/

Show the result. Do not claim done unless the suite is green; if a
test cannot pass, say why instead of weakening the assertion.
