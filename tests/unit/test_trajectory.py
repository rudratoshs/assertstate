"""Trajectory check (FEATURE-SPEC §3, [P2]): parse + evaluate over the TRUSTED capture only.

The evaluator must read BrowserObservations.network (never the agent trace: INV-8) and must be
NON-GATING when no trusted capture is present (status != "captured").
"""

from __future__ import annotations

import inspect

import pytest

from assertstate.contract.errors import ContractError
from assertstate.contract.loader import _parse_trajectory
from assertstate.domain.contract import HttpMatch
from assertstate.domain.trace import BrowserObservations
from assertstate.verifier.policy_engine.sequence import evaluate_trajectory


def _obs(records, status="captured"):
    return BrowserObservations(network=tuple(records), status=status)


def _rec(method, url, started_at, completed_at=None):
    return {
        "method": method,
        "url": url,
        "status": "captured",
        "started_at": started_at,
        "completed_at": completed_at if completed_at is not None else started_at + 0.1,
    }


# --------------------------------------------------------------------------- parse


def test_parse_ordered_requires_two_steps():
    with pytest.raises(ContractError, match=r"needs >=2 steps"):
        _parse_trajectory([{"require": [{"path_glob": "/a"}], "ordered": True}])


def test_parse_unordered_single_step_ok():
    out = _parse_trajectory([{"require": [{"path_glob": "/a"}], "ordered": False}])
    assert out[0].ordered is False
    assert out[0].steps[0].path_glob == "/a"


def test_parse_defaults_ordered_true_and_builds_httpmatch():
    out = _parse_trajectory(
        [{"require": [{"method": "post", "path_glob": "/api/x*"}, {"path_glob": "/api/y"}]}]
    )
    assert out[0].ordered is True
    assert out[0].steps[0] == HttpMatch(method="post", path_glob="/api/x*", status=())


def test_parse_rejects_empty_require():
    with pytest.raises(ContractError, match=r"non-empty list"):
        _parse_trajectory([{"require": []}])


def test_parse_rejects_step_without_path_glob():
    with pytest.raises(ContractError, match=r"path_glob"):
        _parse_trajectory([{"require": [{"method": "get"}], "ordered": False}])


def test_parse_rejects_unknown_fields():
    with pytest.raises(ContractError, match=r"unknown field"):
        _parse_trajectory([{"require": [{"path_glob": "/a"}], "oops": 1}])


# --------------------------------------------------------------------------- evaluate


def test_ordered_satisfied_does_not_fire():
    check = _parse_trajectory(
        [{"require": [{"path_glob": "/api/reserve"}, {"path_glob": "/api/pay"}]}]
    )[0]
    obs = _obs(
        [_rec("POST", "http://app/api/reserve", 1.0), _rec("POST", "http://app/api/pay", 2.0)]
    )
    res = evaluate_trajectory(check, obs)
    assert res.fired is False and res.gating is True


def test_ordered_violation_fires():
    check = _parse_trajectory(
        [{"require": [{"path_glob": "/api/reserve"}, {"path_glob": "/api/pay"}]}]
    )[0]
    # pay happened BEFORE reserve -> ordered requirement not met
    obs = _obs(
        [_rec("POST", "http://app/api/pay", 1.0), _rec("POST", "http://app/api/reserve", 2.0)]
    )
    res = evaluate_trajectory(check, obs)
    assert res.fired is True and res.gating is True


def test_missing_required_step_fires():
    check = _parse_trajectory(
        [{"require": [{"path_glob": "/api/reserve"}, {"path_glob": "/api/pay"}]}]
    )[0]
    obs = _obs([_rec("POST", "http://app/api/reserve", 1.0)])  # no /api/pay
    res = evaluate_trajectory(check, obs)
    assert res.fired is True


def test_unordered_all_present_does_not_fire_regardless_of_order():
    check = _parse_trajectory(
        [{"require": [{"path_glob": "/api/a"}, {"path_glob": "/api/b"}], "ordered": False}]
    )[0]
    obs = _obs([_rec("GET", "http://app/api/b", 2.0), _rec("GET", "http://app/api/a", 1.0)])
    assert evaluate_trajectory(check, obs).fired is False


def test_method_mismatch_counts_as_missing():
    check = _parse_trajectory(
        [{"require": [{"method": "post", "path_glob": "/api/a"}], "ordered": False}]
    )[0]
    obs = _obs([_rec("GET", "http://app/api/a", 1.0)])
    assert evaluate_trajectory(check, obs).fired is True


def test_glob_prefix_match():
    check = _parse_trajectory([{"require": [{"path_glob": "/api/orders/*"}], "ordered": False}])[0]
    obs = _obs([_rec("GET", "http://app/api/orders/42", 1.0)])
    assert evaluate_trajectory(check, obs).fired is False


# ------------------------------------------------------------------- INV-8 / gating


def test_non_gating_without_capture():
    """No trusted capture -> recorded but NON-GATING (never a silent FAIL)."""
    check = _parse_trajectory(
        [{"require": [{"path_glob": "/api/reserve"}, {"path_glob": "/api/pay"}]}]
    )[0]
    obs = _obs([], status="out_of_scope_p0")  # violation present (nothing happened) ...
    res = evaluate_trajectory(check, obs)
    assert res.fired is True  # the requirement is unmet ...
    assert res.gating is False  # ... but it may NOT gate a FAIL without a trusted capture


def test_evaluator_reads_observations_not_agent_trace():
    """INV-8 guard: evaluate_trajectory's only trace input is BrowserObservations."""
    sig = inspect.signature(evaluate_trajectory)
    params = list(sig.parameters.values())
    assert [p.annotation for p in params] == ["TrajectoryCheck", "BrowserObservations"]
    # The only trace input is the trusted BrowserObservations; the agent's own trace never enters.
    src = inspect.getsource(evaluate_trajectory)
    assert "AgentTrace" not in src
    assert "observations.network" in src  # verdict is read from the trusted capture
