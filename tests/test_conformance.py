"""Two-path conformance on a fast subset (full 18-case run:
conformance/run_conformance.py). The served path must answer
byte-identically to the in-process path — same agent module, so any
divergence is a port bug, not model drift. Offline composer forced.
"""
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
    os.environ.pop(var, None)

from agentcore_port.agent_loader import load_agent  # noqa: E402
from agentcore_port.runtime import SESSION_HEADER, AgentCoreRuntime, make_server  # noqa: E402
from agentcore_port.trace import TraceSink  # noqa: E402

CASES = [json.loads(line) for line in
         (Path(__file__).resolve().parent.parent / "conformance" / "cases.jsonl")
         .read_text(encoding="utf-8").splitlines() if line.strip()]
SUBSET = [c for c in CASES if c["id"] in
          ("state-graph", "checkpointing-enables", "abstain-cooking",
           "abstain-weather")]


def test_two_paths_identical_on_subset():
    agent = load_agent()
    sink = TraceSink()
    runtime = AgentCoreRuntime(run_agent=agent.run_agent, trace_sink=sink)
    server = make_server(runtime, host="127.0.0.1", port=0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for i, case in enumerate(SUBSET):
            direct = agent.run_agent(case["question"])
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/invocations",
                data=json.dumps({"prompt": case["question"]}).encode(),
                headers={"Content-Type": "application/json",
                         SESSION_HEADER: f"conformance-test-{i}-0123456789abcdef"},
                method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                served = json.loads(resp.read().decode())
            assert served["answer"] == direct["answer"], case["id"]
            assert served["plan"] == direct["plan"], case["id"]
            assert served["grounded"] == bool(direct["grounded"]), case["id"]
            assert served["abstained"] == bool(
                direct.get("abstained") or not direct.get("grounded")), case["id"]
    finally:
        server.shutdown()
