"""P1 `bounded` settlement end-to-end through the orchestrator (no LLM).

A scripted HTTP agent routes its 'Pay' through the TRUSTED capture proxy, giving bounded a
real last-causal-request anchor. Bounded waits max_wait (2s > the 0.5s worker retry), so the
duplicate is observable -> db_delta fires -> FAIL. With the proxy bypassed there is no
trusted anchor -> bounded fails closed -> ERROR.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from assertstate.contract.loader import load_and_validate
from assertstate.domain.result import Outcome
from assertstate.domain.verdict import RunOutcome
from assertstate.orchestrator.runner import run_contract

REPO = Path(__file__).resolve().parents[2]
CONTRACT = str(REPO / "contracts" / "pay-invoice.bounded.yaml")
HTTP_ADAPTER = "assertstate.adapters.http_demo_adapter:HttpDemoAdapter"


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


def _contract():
    c, report = load_and_validate(CONTRACT)
    assert c is not None, report.errors
    return c


def test_bounded_settles_via_trusted_anchor_and_catches_duplicate() -> None:
    env = _bounded_env(buggy=True, route_through_proxy=True)
    out = run_contract(_contract(), env, HTTP_ADAPTER, trials=3)
    assert all(t.outcome is Outcome.FAIL for t in out.trials), [t.reason for t in out.trials]
    # settlement was bounded, anchored on a trusted request time
    rec = out.trials[0].settlement
    assert rec is not None and rec.mode == "bounded" and rec.causal_start_at is not None
    assert out.verdict.verdict is RunOutcome.FAIL


def test_bounded_fails_closed_without_trusted_timing() -> None:
    # Agent bypasses the proxy -> no trusted anchor -> bounded -> ERROR (never a silent pass).
    env = _bounded_env(buggy=True, route_through_proxy=False)
    out = run_contract(_contract(), env, HTTP_ADAPTER, trials=1)
    assert out.trials[0].outcome is Outcome.ERROR
    assert "anchor" in out.trials[0].reason
