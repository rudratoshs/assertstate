"""Trajectory policy end-to-end through a capture-wired environment (FEATURE-SPEC §3, P2).

The scripted HTTP agent routes GET `/` then POST `/pay` through the TRUSTED capture proxy, so
the trajectory is evaluated over real parent-owned records (never the agent trace -> INV-8):
  - a satisfied ordering does not fire -> PASS;
  - a required-but-never-called step fires AND gates -> FAIL;
  - an agent that BYPASSES the attached trusted proxy leaves the required request unobserved, so
    it still FAILs (fail-closed: the trusted oracle can only credit what it observed, never the
    agent's say-so). The genuinely NON-GATING case is when NO capture is attached at all (a real
    app with `capture: off` / https) — covered in tests/unit/test_trajectory.py and
    tests/integration/test_configured_env.py.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from assertstate.contract.loader import load_and_validate
from assertstate.domain.result import Outcome
from assertstate.orchestrator.runner import run_contract

REPO = Path(__file__).resolve().parents[2]
HTTP_ADAPTER = "assertstate.adapters.http_demo_adapter:HttpDemoAdapter"

_STATS = "statistics: { trials: 1, pass_threshold: 0.5, min_valid_trials: 1, max_error_rate: 1.0 }"


def _pg() -> bool:
    try:
        return subprocess.run(["pg_isready", "-h", "/tmp"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _pg(), reason="no local Postgres reachable")


def _bounded_env(**kw: object):
    demo = REPO / "demo-app"
    if str(demo) not in sys.path:
        sys.path.insert(0, str(demo))
    from bounded_environment import BoundedDemoEnvironment  # type: ignore[import-not-found]

    return BoundedDemoEnvironment(**kw)


def _contract(trajectory_yaml: str):
    body = f"task: t\napp: demo\n{trajectory_yaml}\n{_STATS}\n"
    fh = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    fh.write(body)
    fh.close()
    c, report = load_and_validate(fh.name)
    assert c is not None, report.errors
    return c


_SATISFIED = (
    "trajectory:\n"
    "  - require:\n"
    "      - { method: GET, path_glob: / }\n"
    "      - { method: POST, path_glob: /pay* }\n"
    "    ordered: true"
)
_VIOLATED = "trajectory:\n  - require:\n      - { path_glob: /refund* }\n    ordered: false"


def test_satisfied_trajectory_passes() -> None:
    env = _bounded_env(buggy=False, route_through_proxy=True)
    out = run_contract(_contract(_SATISFIED), env, HTTP_ADAPTER, trials=1)
    assert out.trials[0].outcome is Outcome.PASS, out.trials[0].reason


def test_violated_trajectory_fails_when_captured() -> None:
    env = _bounded_env(buggy=False, route_through_proxy=True)
    out = run_contract(_contract(_VIOLATED), env, HTTP_ADAPTER, trials=1)
    assert out.trials[0].outcome is Outcome.FAIL, out.trials[0].reason


def test_bypassing_attached_proxy_still_fails_a_required_step() -> None:
    # A trusted capture IS attached but the agent bypasses it -> the required request is never
    # observed -> FAIL. Fail-closed: the oracle credits only what it observed, never the agent.
    env = _bounded_env(buggy=False, route_through_proxy=False)
    out = run_contract(_contract(_SATISFIED), env, HTTP_ADAPTER, trials=1)
    assert out.trials[0].outcome is Outcome.FAIL, out.trials[0].reason
