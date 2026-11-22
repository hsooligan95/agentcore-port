#!/usr/bin/env python3
"""Serve factory-floor-agent through the AgentCore Runtime contract.

Usage:
    python serve.py [--host 0.0.0.0] [--port 8080]

Then, exactly as an InvokeAgentRuntime caller would:
    curl localhost:8080/ping
    curl -X POST localhost:8080/invocations \
        -H 'Content-Type: application/json' \
        -H 'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: <33-256 chars>' \
        -d '{"prompt": "What is a state graph in LangGraph?"}'

Environment:
    FACTORY_FLOOR_AGENT_HOME  factory-floor-agent checkout (default: sibling)
    AGENTTRACE_TRACE_ID       propagated trace ID for emitted events
    AGENTCORE_PORT_TRACE_OUT  JSONL path for AgentTrace events
                              (default: ./agentcore-port-trace.jsonl)
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agentcore_port.runtime import AgentCoreRuntime, make_server  # noqa: E402
from agentcore_port.trace import TraceSink  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    sink = TraceSink(os.environ.get("AGENTCORE_PORT_TRACE_OUT",
                                    "agentcore-port-trace.jsonl"))
    runtime = AgentCoreRuntime(trace_sink=sink)
    server = make_server(runtime, host=args.host, port=args.port)
    print(f"AgentCore Runtime contract on {args.host}:{args.port} "
          "(/invocations, /ping) — local harness, no AWS calls")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
