"""Out-of-process adapter runner — the trusted parent side (SYSTEM-DESIGN §2; DEVELOPMENT §10).

Spawns the untrusted adapter in a child subprocess and enforces the boundary mechanically:
  - child env is an ALLOWLIST (no ORACLE_*/ASSERTSTATE_*/secrets)                  [INV-3]
  - IPC is JSON only (no pickle / no Python objects cross)                          [INV-4]
  - only {task, browser_target, execution_budget, run_id} go in                     [INV-5]
  - only {steps, agent_claimed_done} come back, validated strictly                  [INV-6]
  - malformed / oversized / crash / timeout -> AdapterError (-> trial ERROR)
Scope: a subprocess + filtered env backs INV-3..6. Full filesystem/socket isolation
(INV-7) is the P1 container hardening and is NOT claimed here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from assertstate.adapters.base import AdapterError
from assertstate.domain.trace import AgentTrace

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR")
_DEFAULT_MAX_BYTES = 8 * 1024 * 1024


def _child_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
    # The child must be able to import `assertstate` and `tests` but carries NO secrets.
    env["PYTHONPATH"] = str(_REPO_ROOT)
    # Agent-side credentials (e.g. the LLM key) are passed EXPLICITLY by the caller — these
    # are the agent's own creds, like a browser login. A hard guard still refuses anything
    # oracle-shaped, so an environment can never smuggle the oracle DSN to the agent.
    for k, v in (extra_env or {}).items():
        if k.upper().startswith("ORACLE") or "oracle" in k.lower():
            raise AdapterError(f"refusing to pass oracle-shaped credential {k!r} to the agent")
        env[k] = v
    return env


def run_adapter(
    adapter_spec: str,
    *,
    task: str,
    browser_target: dict[str, Any],
    execution_budget: dict[str, Any],
    run_id: str,
    timeout_s: float = 30.0,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    extra_env: dict[str, str] | None = None,
) -> AgentTrace:
    """Run `adapter_spec` ("module:attr") in a child process and return its AgentTrace."""
    request = json.dumps(
        {
            "task": task,
            "browser_target": browser_target,
            "execution_budget": execution_budget,
            "run_id": run_id,
        }
    )
    cmd = [sys.executable, "-m", "assertstate.adapters.child", adapter_spec]
    try:
        proc = subprocess.run(
            cmd,
            input=request,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=_child_env(extra_env),
            cwd=str(_REPO_ROOT),
        )
    except subprocess.TimeoutExpired as exc:
        raise AdapterError(f"adapter timed out after {timeout_s}s") from exc

    if proc.returncode != 0:
        raise AdapterError(f"adapter exited {proc.returncode}: {proc.stderr[:500]}")
    if len(proc.stdout) > max_bytes:
        raise AdapterError(f"adapter output exceeded {max_bytes} bytes")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"adapter output is not JSON: {proc.stdout[:200]!r}") from exc

    if not isinstance(payload, dict) or set(payload) != {"steps", "agent_claimed_done"}:
        shape = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
        raise AdapterError(f"adapter output has wrong shape: {shape}")
    if not isinstance(payload["steps"], list) or not isinstance(
        payload["agent_claimed_done"], bool
    ):
        raise AdapterError("adapter output field types are wrong")

    return AgentTrace(
        steps=tuple(payload["steps"]),
        agent_claimed_done=payload["agent_claimed_done"],
    )
