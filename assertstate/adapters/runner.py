"""Out-of-process adapter runner — the trusted parent side (SYSTEM-DESIGN §2; DEVELOPMENT §10).

Spawns the untrusted adapter in a child subprocess and enforces the boundary mechanically:
  - child env is an ALLOWLIST (no ORACLE_*/ASSERTSTATE_*/secrets)                  [INV-3]
  - IPC is JSON only (no pickle / no Python objects cross)                          [INV-4]
  - only {task, browser_target, execution_budget, run_id} go in                     [INV-5]
  - only {steps, agent_claimed_done} come back, validated strictly                  [INV-6]
  - malformed / oversized / crash / timeout -> AdapterError (-> trial ERROR)
Scope: mode="subprocess" backs INV-3..6 via a filtered env. mode="container" adds INV-7
(host-FS + privilege isolation: no host mount, non-root, --read-only, --cap-drop ALL) by running
the child in a locked-down `docker run` container. The CLI's real (`--config`) run path engages
the container by DEFAULT (`--sandbox auto`), with a recorded subprocess fallback only when Docker
is unreachable; the strict `--network none` posture is the adversarial INV-7 proof (and the posture
for network-free adapters), while a real networked agent uses `--network bridge` (the oracle stays
unreachable because its credential is never passed). The bundled demo (`--app demo`) is a
host-coupled in-process fixture that proves the verdict logic, not the sandbox.
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


def _container_image() -> str:
    # Default image suits the no-LLM adapters (noop / http demo — stdlib only). A real browser
    # agent needs an image carrying its runtime (e.g. Chrome); set ASSERTSTATE_SANDBOX_IMAGE.
    return os.environ.get("ASSERTSTATE_SANDBOX_IMAGE", "python:3.11-slim")


def _container_cmd(
    adapter_spec: str, extra_env: dict[str, str] | None, *, network: str = "none"
) -> list[str]:
    """`docker run` the child in a locked-down container (INV-7).

    Host filesystem isolation (no mount of .assertstate/secrets/host files), non-root, read-only
    rootfs, all caps dropped, and the oracle DSN env-stripped hold in EVERY profile. `network`
    selects the socket posture: "none" (the adversarial proof + network-free adapters — trusted
    sockets provably unreachable) or e.g. "bridge" (a real networked agent that must reach the
    app-under-test; the trusted oracle stays unreachable because its credential is never passed).
    """
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        network,  # "none" = full socket isolation (INV-7 proof); "bridge" = networked agent
        "--user",
        "65534:65534",  # nobody
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--cap-drop",
        "ALL",
        "-e",
        "PYTHONPATH=/app",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
    ]
    for k, v in (extra_env or {}).items():  # agent creds only (oracle-guard applied in _child_env)
        if k.upper().startswith("ORACLE") or "oracle" in k.lower():
            raise AdapterError(f"refusing to pass oracle-shaped credential {k!r} to the agent")
        cmd += ["-e", f"{k}={v}"]
    cmd += [
        "-v",
        f"{_REPO_ROOT / 'assertstate'}:/app/assertstate:ro",
        "-v",
        f"{_REPO_ROOT / 'tests'}:/app/tests:ro",  # for adversarial test adapters
        _container_image(),
        "python",
        "-m",
        "assertstate.adapters.child",
        adapter_spec,
    ]
    return cmd


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
    mode: str = "subprocess",
    container_network: str = "none",
) -> AgentTrace:
    """Run `adapter_spec` ("module:attr") out-of-process and return its AgentTrace.

    mode="subprocess" (default) backs INV-3/4/5/6 via env filtering. mode="container" adds INV-7
    (host-FS/privilege isolation) by running the child in a locked-down container; container_network
    selects its socket posture ("none" = full isolation / adversarial proof; "bridge" = a real
    agent that must reach the app, with the trusted DB credential never passed so it stays
    unreachable).
    """
    request = json.dumps(
        {
            "task": task,
            "browser_target": browser_target,
            "execution_budget": execution_budget,
            "run_id": run_id,
        }
    )
    if mode == "container":
        cmd = _container_cmd(adapter_spec, extra_env, network=container_network)
        env = None  # docker provides the container env; -e flags carry agent creds
        cwd = None
    else:
        cmd = [sys.executable, "-m", "assertstate.adapters.child", adapter_spec]
        env = _child_env(extra_env)
        cwd = str(_REPO_ROOT)
    try:
        proc = subprocess.run(
            cmd,
            input=request,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            cwd=cwd,
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
