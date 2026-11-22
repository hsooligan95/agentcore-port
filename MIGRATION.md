# Migrating an agent from Lambda/Fargate to AgentCore Runtime

The comparison A2Z Sync's posting asks about, written from this port.
The workload is factory-floor-agent: a LangGraph QA agent that today
runs in-process (a CLI) — the same position a Lambda handler or a
Fargate task starts from.

## What does NOT change

- **The agent itself.** Graph, retrieval, groundedness check, abstain
  behaviour: untouched. The conformance run in this repo exists to prove
  that sentence — 18/18 eval cases, byte-identical answers on both
  paths.
- **The request/response vocabulary.** Callers still send a prompt and
  get an answer object. Only the envelope (endpoint, headers) changes.
- **Dependencies.** Same Python requirements. AgentCore's direct code
  upload and container routes both run the same artifact a Fargate task
  would.

## What changes

| Concern | Lambda / Fargate | AgentCore Runtime |
|---|---|---|
| Invocation shape | Lambda event / your own HTTP API | Fixed contract: `POST /invocations`, `GET /ping`, port 8080 |
| Session isolation | You build it (or share a process) | One microVM per session id; the session header routes |
| Session lifetime | Lambda: ~15 min max, stateless between calls | Up to 8 hours; idle timeout ends the session (`Healthy` vs `HealthyBusy` is how you say "keep me alive, I'm working") |
| Conversation memory | DIY (DynamoDB/ElastiCache + your schema) | AgentCore Memory: managed event store + retrieval strategies behind an API |
| Caller identity | IAM / your own auth layer | AgentCore Identity: workload identity + OAuth token vending for inbound and outbound |
| Tool access | Direct calls from your code | Optionally through AgentCore Gateway (MCP targets, interceptors) — NOT part of this port; agent-gate's policy model is the local analogue |
| Scaling unit | Concurrent executions / tasks | Sessions (microVMs) — cold-start and cost thinking follows sessions, not requests |
| IAM | Execution role per function/task | Execution role per runtime — least-privilege discipline is identical, the policy in `infra/` shows the delta |

## The honest caveat

The left column is experience; the right column is, in this repo, a
**locally emulated contract plus untested templates**. The contract
behaviour (endpoints, headers, ping semantics, session validation) is
implemented and conformance-tested locally. The managed behaviours that
only exist inside AWS — microVM isolation, Memory's semantic retrieval,
Identity's token vending, Gateway — are represented by interface-shaped
stubs and labeled as such. A live deploy is one documented step
(`infra/`) away and requires an AWS sandbox account; it has not been
run, and this document does not pretend otherwise.
