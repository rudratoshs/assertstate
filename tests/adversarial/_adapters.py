"""Malicious / misbehaving adapters for the boundary suite (run in the untrusted child)."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

from assertstate.domain.trace import AgentTrace


class LeakAdapter:
    """Honest-looking adapter that reports what secrets/env it can actually see."""

    def run(
        self, task: str, browser_target: dict[str, Any], budget: dict[str, Any], run_id: str
    ) -> AgentTrace:
        return AgentTrace(
            steps=(
                {
                    "oracle_dsn_env": os.environ.get("ORACLE_DSN"),
                    "assertstate_env_keys": sorted(
                        k for k in os.environ if k.startswith("ASSERTSTATE_")
                    ),
                    "saw_oracle_in_target": any("oracle" in str(k).lower() for k in browser_target),
                    "env_key_count": len(os.environ),
                },
            ),
            agent_claimed_done=True,
        )


class BadShapeAdapter:
    """Emits an AgentTrace-ish object with an extra smuggled key, bypassing serialization."""

    def run(
        self, task: str, browser_target: dict[str, Any], budget: dict[str, Any], run_id: str
    ) -> AgentTrace:
        sys.stdout.write(json.dumps({"steps": [], "agent_claimed_done": True, "stolen": "secret"}))
        sys.stdout.flush()
        os._exit(0)


class GarbageAdapter:
    def run(
        self, task: str, browser_target: dict[str, Any], budget: dict[str, Any], run_id: str
    ) -> AgentTrace:
        sys.stdout.write("this is not json at all")
        sys.stdout.flush()
        os._exit(0)


class HugeAdapter:
    def run(
        self, task: str, browser_target: dict[str, Any], budget: dict[str, Any], run_id: str
    ) -> AgentTrace:
        sys.stdout.write("x" * (20 * 1024 * 1024))
        sys.stdout.flush()
        os._exit(0)


class CrashAdapter:
    def run(
        self, task: str, browser_target: dict[str, Any], budget: dict[str, Any], run_id: str
    ) -> AgentTrace:
        os._exit(3)


class TimeoutAdapter:
    def run(
        self, task: str, browser_target: dict[str, Any], budget: dict[str, Any], run_id: str
    ) -> AgentTrace:
        time.sleep(30)
        return AgentTrace(steps=(), agent_claimed_done=True)


class SlowAdapter:
    """Succeeds but burns wall time (browser_target['sleep_s']) to exceed a small max_seconds."""

    def run(
        self, task: str, browser_target: dict[str, Any], budget: dict[str, Any], run_id: str
    ) -> AgentTrace:
        time.sleep(float(browser_target.get("sleep_s", 1.0)))
        return AgentTrace(steps=({"action": "slow"},), agent_claimed_done=True)


class HonestAdapter:
    def run(
        self, task: str, browser_target: dict[str, Any], budget: dict[str, Any], run_id: str
    ) -> AgentTrace:
        return AgentTrace(steps=({"action": "noop"},), agent_claimed_done=True)


class FsProbeAdapter:
    """Tries to read a host path (passed via browser_target). In a container it is unreachable."""

    def run(
        self, task: str, browser_target: dict[str, Any], budget: dict[str, Any], run_id: str
    ) -> AgentTrace:
        path = browser_target.get("probe_path", "/nonexistent")
        try:
            data = open(path, encoding="utf-8").read(64)  # noqa: SIM115
            reachable = True
        except OSError as exc:
            data = str(exc)
            reachable = False
        return AgentTrace(
            steps=({"probe_path": path, "reachable": reachable, "detail": data[:80]},),
            agent_claimed_done=True,
        )


class SocketProbeAdapter:
    """Tries to connect to a trusted socket (host:port via browser_target); no network => fail."""

    def run(
        self, task: str, browser_target: dict[str, Any], budget: dict[str, Any], run_id: str
    ) -> AgentTrace:
        import socket

        host = browser_target.get("probe_host", "127.0.0.1")
        port = int(browser_target.get("probe_port", 0))
        try:
            with socket.create_connection((host, port), timeout=2):
                reachable = True
                detail = "connected"
        except OSError as exc:
            reachable = False
            detail = str(exc)
        return AgentTrace(
            steps=(
                {"probe_hostport": f"{host}:{port}", "reachable": reachable, "detail": detail[:80]},
            ),
            agent_claimed_done=True,
        )
