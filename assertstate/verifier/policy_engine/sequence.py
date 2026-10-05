"""Trajectory check — "must call X before Y" (FEATURE-SPEC §3, `[P2, secondary]`).

Evaluated over the TRUSTED BrowserObservations network (ordered by request start), NEVER over the
agent's trace — so it cannot be driven by the agent's self-report (INV-8). Like the http/external
policies it is GATING only when a trusted capture is present (`observations.status == "captured"`);
without capture it is recorded NON-GATING (never a silent pass, never a false FAIL).

FIRES (→ contributes FAIL) when the required sequence is NOT satisfied: a required step never
occurred, or (ordered) the required order was violated.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from assertstate.domain.contract import HttpMatch, TrajectoryCheck
from assertstate.domain.trace import BrowserObservations
from assertstate.verifier.policy_engine.base import PolicyResult


def _path_matches(glob: str, path: str) -> bool:
    return path.startswith(glob[:-1]) if glob.endswith("*") else path == glob


def _step_matches(step: HttpMatch, rec: dict[str, Any]) -> bool:
    if step.method and str(rec.get("method", "")).upper() != step.method.upper():
        return False
    return _path_matches(step.path_glob, urlparse(str(rec.get("url", ""))).path)


def evaluate_trajectory(check: TrajectoryCheck, observations: BrowserObservations) -> PolicyResult:
    gating = observations.status == "captured"
    # Order the trusted records by when each request started.
    recs = sorted(observations.network, key=lambda r: r.get("started_at") or 0.0)

    if check.ordered:
        # Each step's first match must START at/after the previous step's match COMPLETED.
        cursor = 0.0
        matched = 0
        for step in check.steps:
            hit = next(
                (
                    r
                    for r in recs
                    if (r.get("started_at") or 0.0) >= cursor and _step_matches(step, r)
                ),
                None,
            )
            if hit is None:
                break
            matched += 1
            cursor = hit.get("completed_at") or hit.get("started_at") or cursor
        satisfied = matched == len(check.steps)
    else:
        satisfied = all(any(_step_matches(step, r) for r in recs) for step in check.steps)
        matched = sum(1 for step in check.steps if any(_step_matches(step, r) for r in recs))

    fired = not satisfied  # the required trajectory did not hold
    detail = (
        f"trajectory[ordered={check.ordered}] matched={matched}/{len(check.steps)} "
        f"satisfied={satisfied} fired={fired} gating={gating} capture={observations.status}"
    )
    return PolicyResult(kind="trajectory", fired=fired, gating=gating, detail=detail)
