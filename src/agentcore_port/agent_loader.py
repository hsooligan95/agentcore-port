"""Load the factory-floor-agent's agent module — the SAME code both ways.

The port does not copy or reimplement the agent. It locates the
factory-floor-agent checkout (env ``FACTORY_FLOOR_AGENT_HOME``, else the
sibling directory ``../factory-floor-agent``), puts its ``src/`` on
``sys.path``, and imports its ``agent`` module. The in-process path and
the HTTP-served path both call that module's ``run_agent`` — which is
what makes the two-path conformance test a statement about the port,
not about two implementations drifting apart.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


class AgentNotFoundError(RuntimeError):
    pass


def agent_home() -> Path:
    env = os.environ.get("FACTORY_FLOOR_AGENT_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path(__file__).resolve().parents[3] / "factory-floor-agent").resolve()


def load_agent():
    """Import and return factory-floor-agent's ``agent`` module."""
    home = agent_home()
    src = home / "src"
    if not (src / "agent.py").is_file():
        raise AgentNotFoundError(
            f"factory-floor-agent not found at {home} "
            "(set FACTORY_FLOOR_AGENT_HOME to its checkout)"
        )
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return importlib.import_module("agent")
