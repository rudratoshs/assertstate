"""expect.db evaluator (FEATURE-SPEC §4.1/§4.5; DEVELOPMENT.md §22).

Reads final state through the read-only oracle and applies the comparator. Supports
`eventually` polling for db. Deterministic over the captured reads; oracle failure
propagates as OracleError (-> trial ERROR), never a silent pass.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from assertstate.domain.comparator import Comparator
from assertstate.domain.contract import ApiExpect, DbExpect
from assertstate.oracle.api_probe.probe import ApiProbe
from assertstate.oracle.db_probe.probe import DbProbe
from assertstate.verifier.expect.comparators import compare
from assertstate.verifier.jsonpath import extract


@dataclass(frozen=True)
class ExpectResult:
    query: str
    ok: bool
    present: bool
    observed: Any
    detail: str


def _check_once(e: DbExpect, probe: DbProbe) -> ExpectResult:
    res = probe.select(e.query)  # OracleError -> ERROR upstream
    present = bool(res.rows)
    observed = next(iter(res.rows[0].values())) if present else None

    if e.comparator is Comparator.ABSENT:
        ok = (not present) or (observed is None)
        return ExpectResult(
            e.query, ok, present, observed, "absent" if ok else "unexpectedly present"
        )
    if e.comparator is Comparator.ANY:
        return ExpectResult(e.query, present, present, observed, "present" if present else "no row")

    if not present:
        return ExpectResult(e.query, False, False, None, "no row to compare")
    if observed is None:
        return ExpectResult(e.query, False, True, None, "observed value is NULL")

    ok = compare(e.comparator, observed, e.value)
    return ExpectResult(
        e.query, ok, True, observed, f"{observed!r} {e.comparator.value} {e.value!r} -> {ok}"
    )


def evaluate_db_expect(probe: DbProbe, e: DbExpect) -> ExpectResult:
    """Evaluate one expect.db, polling under `eventually` until it holds or the window ends."""
    result = _check_once(e, probe)
    if result.ok or e.eventually is None:
        return result
    deadline = time.monotonic() + e.eventually.timeout_ms / 1000.0
    poll_s = e.eventually.poll_ms / 1000.0
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        result = _check_once(e, probe)
        if result.ok:
            return result
    return result


def _check_api_once(e: ApiExpect, probe: ApiProbe) -> ExpectResult:
    method, _, path = e.request.strip().partition(" ")
    res = probe.request(method, path or "/")  # OracleError -> ERROR upstream
    present, observed = extract(e.jsonpath, res.json) if res.json is not None else (False, None)
    if e.comparator is Comparator.ABSENT:
        ok = not present or observed is None
        return ExpectResult(e.request, ok, present, observed, "absent" if ok else "present")
    if e.comparator is Comparator.ANY:
        return ExpectResult(
            e.request, present, present, observed, "present" if present else "missing"
        )
    if not present or observed is None:
        return ExpectResult(e.request, False, present, observed, f"jsonpath {e.jsonpath} not found")
    ok = compare(e.comparator, observed, e.value)
    return ExpectResult(
        e.request, ok, True, observed, f"{observed!r} {e.comparator.value} {e.value!r}"
    )


def evaluate_api_expect(probe: ApiProbe, e: ApiExpect) -> ExpectResult:
    """Evaluate one expect.api (GET/HEAD + jsonpath + comparator), with eventually polling."""
    result = _check_api_once(e, probe)
    if result.ok or e.eventually is None:
        return result
    deadline = time.monotonic() + e.eventually.timeout_ms / 1000.0
    poll_s = e.eventually.poll_ms / 1000.0
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        result = _check_api_once(e, probe)
        if result.ok:
            return result
    return result
