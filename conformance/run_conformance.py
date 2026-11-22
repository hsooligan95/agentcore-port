#!/usr/bin/env python3
"""Two-path conformance: in-process vs AgentCore-served, same agent.

Runs every eval case (cases.jsonl — the labeled set from
rag-evaluation-harness, copied verbatim) through factory-floor-agent
twice:

  path A  in-process:  agent.run_agent(question), as the agent runs today
  path B  served:      POST /invocations against the local AgentCore
                       Runtime contract harness (ephemeral port), with a
                       session header and a propagated AgentTrace ID

For each case the two paths must agree EXACTLY on answer text, plan,
grounded/abstained outcome, and retrieved sources — and each path is
also scored with the harness's own rules (answerable: expected doc
retrieved + expected term in a grounded, non-abstained answer;
abstention: the agent abstained). Any divergence fails the run.

Both paths force the agent's deterministic offline composer (the
OPENAI_* env vars are cleared for the whole run) — comparing a live
model against itself would measure the model, not the port.

Usage:
    python conformance/run_conformance.py [--json conformance/results/conformance.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
    os.environ.pop(var, None)

from agentcore_port.agent_loader import load_agent  # noqa: E402
from agentcore_port.runtime import AgentCoreRuntime, SESSION_HEADER, make_server  # noqa: E402
from agentcore_port.trace import TraceSink  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "cases.jsonl"
TRACE_ID = "trace-conformance-agentcore-port"


def load_cases() -> list[dict]:
    return [json.loads(line) for line in
            CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def score(case: dict, *, answer: str, grounded: bool, abstained: bool,
          sources: list[str], **_view_extras) -> bool:
    """The rag-evaluation-harness scoring rules, restated."""
    if case["kind"] == "abstention":
        return abstained
    if abstained or not grounded:
        return False
    if not any(case["expected_doc"] in s for s in sources):
        return False
    return any(term.lower() in answer.lower()
               for term in case["expected_terms"])


def post_invocation(port: int, question: str, session_id: str) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/invocations",
        data=json.dumps({"prompt": question}).encode(),
        headers={"Content-Type": "application/json",
                 SESSION_HEADER: session_id,
                 "X-Agenttrace-Trace-Id": TRACE_ID},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=str(
        Path(__file__).resolve().parent / "results" / "conformance.json"))
    args = parser.parse_args()

    agent = load_agent()
    cases = load_cases()

    sink = TraceSink()
    runtime = AgentCoreRuntime(run_agent=agent.run_agent, trace_sink=sink)
    server = make_server(runtime, host="127.0.0.1", port=0)
    port = server.server_address[1]
    import threading
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    rows, divergences = [], []
    try:
        for i, case in enumerate(cases):
            direct = agent.run_agent(case["question"])
            d_abstained = bool(direct.get("abstained") or not direct.get("grounded"))
            d_sources = [h.chunk.doc_id for h in direct.get("hits", [])]
            d_view = {"answer": direct.get("answer", ""), "plan": direct.get("plan"),
                      "grounded": bool(direct.get("grounded")),
                      "abstained": d_abstained, "sources": d_sources}

            served = post_invocation(port, case["question"],
                                     f"conformance-session-{i:02d}-0123456789abcdef")
            s_view = {"answer": served["answer"], "plan": served["plan"],
                      "grounded": served["grounded"],
                      "abstained": served["abstained"],
                      # served path reports the same doc ids via its
                      # agent_run AgentTrace event
                      "sources": [h["doc_id"] for h in
                                  sink.events[-2]["payload"]["hits"]]}

            identical = d_view == s_view
            if not identical:
                divergences.append(case["id"])
            rows.append({
                "id": case["id"], "kind": case["kind"], "identical": identical,
                "direct_pass": score(case, **d_view),
                "served_pass": score(case, **s_view),
            })
    finally:
        server.shutdown()

    summary = {
        "trace_id": TRACE_ID,
        "cases": len(rows),
        "identical": sum(r["identical"] for r in rows),
        "divergences": divergences,
        "direct_passed": sum(r["direct_pass"] for r in rows),
        "served_passed": sum(r["served_pass"] for r in rows),
        "trace_events_emitted": len(sink.events),
        "rows": rows,
    }
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"cases: {summary['cases']}  identical: {summary['identical']}"
          f"  divergences: {divergences or 'none'}")
    print(f"scored pass — in-process: {summary['direct_passed']}/{len(rows)}"
          f"  served: {summary['served_passed']}/{len(rows)}")
    print(f"AgentTrace events emitted by the served path: {len(sink.events)}"
          f" (trace {TRACE_ID})")
    ok = not divergences and summary["direct_passed"] == summary["served_passed"]
    print("CONFORMANCE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
