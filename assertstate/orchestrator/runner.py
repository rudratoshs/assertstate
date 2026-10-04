"""Run orchestrator — the canonical per-trial lifecycle (SYSTEM-DESIGN §5; DEVELOPMENT §9).

isolate -> seed/preconditions -> baseline -> act(adapter, out-of-process) -> settle(drain)
-> after -> verify(expect + db_delta) -> record -> aggregate.

The verdict is computed only from the oracle + settled deltas; AgentTrace.agent_claimed_done
is recorded as evidence and never gates (INV-8). Any inability to establish correctness
(snapshot unusable, oracle/adapter/settlement failure) is ERROR, never FAIL.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from assertstate.adapters.base import AdapterError
from assertstate.adapters.runner import run_adapter
from assertstate.domain.contract import (
    ApiExpect,
    Contract,
    DbDeltaPolicy,
    DbExpect,
    ExternalPolicy,
    HttpPolicy,
)
from assertstate.domain.result import Attribution, Outcome, SettlementRecord, TrialResult
from assertstate.domain.snapshot import Snapshot
from assertstate.domain.trace import AgentTrace, BrowserObservations
from assertstate.domain.verdict import RunVerdict
from assertstate.env.seed import preconditions_established, verify_preconditions
from assertstate.instrumentation.observations import observations_from_capture
from assertstate.oracle.api_probe.probe import ApiProbe
from assertstate.oracle.db_probe.probe import DbProbe, OracleError
from assertstate.oracle.delta.engine import DeltaError, diff
from assertstate.oracle.delta.predicate import PredicateError
from assertstate.oracle.settlement.controller import SettlementController, SettlementError
from assertstate.oracle.settlement.queue import QueueProbe
from assertstate.oracle.snapshot.snapshot import SnapshotQuery, take_snapshot
from assertstate.orchestrator.environment import Environment, TrialContext
from assertstate.stats.aggregate import aggregate
from assertstate.verifier.expect.comparators import ComparatorError
from assertstate.verifier.expect.evaluator import evaluate_api_expect, evaluate_db_expect
from assertstate.verifier.jsonpath import JsonPathError
from assertstate.verifier.policy_engine.db_delta import evaluate_db_delta
from assertstate.verifier.policy_engine.external import evaluate_external
from assertstate.verifier.policy_engine.http import evaluate_http


@dataclass
class RunOutput:
    verdict: RunVerdict
    trials: list[TrialResult]


def _delta_specs(contract: Contract) -> list[SnapshotQuery]:
    specs = []
    i = 0
    for policy in contract.forbid:
        if isinstance(policy, DbDeltaPolicy):
            specs.append(SnapshotQuery(query_id=f"f{i}", sql=policy.query, key=policy.key or "id"))
            i += 1
    return specs


def _settle(contract: Contract, probe: DbProbe, ctx: TrialContext) -> SettlementRecord | None:
    """Dispatch the contract's settlement. One settlement per trial (one after-snapshot).

    All-`bounded` -> bounded (needs the trusted capture anchor). Otherwise, if any policy
    requires `drain`, drain (the stronger server-side guarantee). No forbid -> no settle.
    """
    deltas = [p for p in contract.forbid if isinstance(p, DbDeltaPolicy)]
    modes = {p.settle.mode for p in deltas}
    if not modes:
        return None  # http/external policies need no DB settlement

    if modes == {"bounded"}:
        max_wait = max((p.settle.max_wait_s or 0.0) for p in deltas)
        if ctx.capture is not None:
            observations = observations_from_capture(ctx.capture)
        else:
            observations = BrowserObservations()  # no instrumentation -> anchor None -> ERROR
        return SettlementController().bounded(observations, max_wait_s=max_wait)

    drains = [p for p in deltas if p.settle.mode == "drain"]
    if drains:
        timeout = max((p.settle.timeout_s or 10.0) for p in drains)
        return SettlementController().drain(QueueProbe(probe), ctx.run_id, timeout_s=timeout).record
    return None


def _verify(
    contract: Contract,
    baseline: Snapshot,
    after: Snapshot,
    probe: DbProbe,
    attribution: Attribution,
    ctx: TrialContext,
) -> tuple[Outcome, str, list[dict[str, Any]], list[dict[str, Any]]]:
    observations = (
        observations_from_capture(ctx.capture) if ctx.capture is not None else BrowserObservations()
    )
    api_probe = ApiProbe(ctx.api_base, ctx.api_creds) if ctx.api_base else None
    app_hosts = {urlparse(str(ctx.browser_target.get("base_url", ""))).netloc}

    expect_results: list[dict[str, Any]] = []
    expect_ok = True
    for e in contract.expect:
        if isinstance(e, DbExpect):
            r = evaluate_db_expect(probe, e)
        elif isinstance(e, ApiExpect):
            if api_probe is None:
                raise OracleError("expect.api requires an api_base in the app config")
            r = evaluate_api_expect(api_probe, e)
        else:  # pragma: no cover - exhaustive
            raise OracleError(f"unknown expect entry {type(e).__name__}")
        # Safe-by-default fields (comparator/ok/present) identify the check and its outcome with
        # no row data; query (WHERE-PII) and detail (raw observed value) are redacted unless the
        # operator opts them in via redaction.allow_fields (FEATURE-SPEC §11 / DEVELOPMENT §28).
        expect_results.append(
            {
                "comparator": e.comparator.value,
                "ok": r.ok,
                "present": r.present,
                "query": r.query,
                "detail": r.detail,
            }
        )
        expect_ok = expect_ok and r.ok

    policy_results: list[dict[str, Any]] = []
    gating_fired = False
    db_i = 0
    for policy in contract.forbid:
        if isinstance(policy, DbDeltaPolicy):
            qid = f"f{db_i}"
            db_i += 1
            d = diff(qid, baseline.queries[qid], after.queries[qid])
            pr = evaluate_db_delta(policy, d, attribution)
        elif isinstance(policy, HttpPolicy):
            pr = evaluate_http(policy, observations)
        elif isinstance(policy, ExternalPolicy):
            pr = evaluate_external(policy, observations, app_hosts)
        else:  # pragma: no cover - exhaustive
            raise OracleError(f"unknown forbid entry {type(policy).__name__}")
        policy_results.append(
            {"kind": pr.kind, "fired": pr.fired, "gating": pr.gating, "detail": pr.detail}
        )
        if pr.fired and pr.gating:  # observed/uncaptured policies are non-gating (§6.5)
            gating_fired = True

    if not expect_ok or gating_fired:
        reason = f"expect_ok={expect_ok} gating_policy_fired={gating_fired}"
        return Outcome.FAIL, reason, expect_results, policy_results
    return (
        Outcome.PASS,
        "all expect held and no gating policy fired",
        expect_results,
        policy_results,
    )


def _run_trial(
    contract: Contract,
    environment: Environment,
    adapter_spec: str,
    index: int,
    *,
    mode: str = "subprocess",
    container_network: str = "none",
) -> TrialResult:
    ctx: TrialContext | None = None
    try:
        ctx = environment.setup(index)
        probe = DbProbe(ctx.oracle_dsn)

        pcs = verify_preconditions(probe, contract.preconditions)
        if not preconditions_established(pcs):
            detail = "; ".join(f"{p.description}: {p.detail}" for p in pcs if not p.established)
            return TrialResult(
                outcome=Outcome.SKIPPED, reason=f"precondition not established: {detail}"
            )

        specs = _delta_specs(contract)
        baseline = take_snapshot(probe, specs)
        if not baseline.usable:
            return TrialResult(outcome=Outcome.ERROR, reason="baseline snapshot unusable")

        budget = contract.budget
        timeout_s = budget.max_seconds if budget and budget.max_seconds else 30.0
        started_at = time.monotonic()
        trace: AgentTrace = run_adapter(
            adapter_spec,
            task=contract.task,
            browser_target=ctx.browser_target,
            execution_budget={
                "max_steps": budget.max_steps if budget else None,
                "max_cost_usd": budget.max_cost_usd if budget else None,
                "max_seconds": budget.max_seconds if budget else None,
            },
            run_id=ctx.run_id,
            # Kill margin > max_seconds so a natural over-run completes and FAILs (gating, below);
            # only a hang past the margin is killed -> AdapterError -> ERROR.
            timeout_s=timeout_s + 10.0,
            extra_env=ctx.adapter_env or None,  # agent-side creds only; oracle DSN never here
            mode=mode,
            container_network=container_network,
        )
        elapsed_s = time.monotonic() - started_at
        # max_seconds is parent-measured wall time (trusted, INV-8-safe) -> it GATES.
        budget_results: dict[str, Any] = {}
        over_budget = False
        if budget and budget.max_seconds is not None:
            over_budget = elapsed_s > budget.max_seconds
            budget_results = {
                "max_seconds": budget.max_seconds,
                "measured_seconds": round(elapsed_s, 3),
                "over_budget": over_budget,
            }

        settlement = _settle(contract, probe, ctx)

        after = take_snapshot(probe, specs)
        if not after.usable:
            return TrialResult(outcome=Outcome.ERROR, reason="after snapshot unusable")

        attribution = ctx.attribution
        outcome, reason, expect_results, policy_results = _verify(
            contract, baseline, after, probe, attribution, ctx
        )
        # Budget over-run is a trusted, gating failure: a PASS on correctness still FAILs if the
        # agent exceeded max_seconds (F4). ERROR outcomes are left as-is (correctness unknown).
        if over_budget and outcome == Outcome.PASS:
            outcome = Outcome.FAIL
            ms = budget_results["measured_seconds"]
            lim = budget_results["max_seconds"]
            reason = f"budget exceeded: {ms}s > max_seconds={lim}; {reason}"
        return TrialResult(
            outcome=outcome,
            reason=reason,
            attribution=attribution,
            expect_results=tuple(expect_results),
            policy_results=tuple(policy_results),
            budget_results=budget_results,
            settlement=settlement,
            refs={"agent_claimed_done": str(trace.agent_claimed_done)},  # recorded, NOT trusted
        )
    # `reason` is an allowlisted evidence field, so it must not carry raw exception text derived
    # from EXTERNAL data. SettlementError is a TRUSTED internal control signal whose message is
    # harness-authored (run_id + integer queue state only), so it is safe to surface. AdapterError
    # (wraps child stderr) and the oracle/verify group (wrap psycopg/DB text) can echo DSNs, SQL,
    # row values or whatever the agent printed, so only their exception TYPE is recorded.
    except SettlementError as exc:
        return TrialResult(outcome=Outcome.ERROR, reason=f"settlement: {exc}")
    except AdapterError as exc:
        return TrialResult(outcome=Outcome.ERROR, reason=f"adapter error ({type(exc).__name__})")
    except (OracleError, DeltaError, PredicateError, ComparatorError, JsonPathError) as exc:
        return TrialResult(
            outcome=Outcome.ERROR, reason=f"verification error ({type(exc).__name__})"
        )
    finally:
        if ctx is not None:
            environment.teardown(ctx)


def run_contract(
    contract: Contract,
    environment: Environment,
    adapter_spec: str,
    *,
    trials: int | None = None,
    mode: str = "subprocess",
    container_network: str = "none",
) -> RunOutput:
    n = trials if trials is not None else contract.statistics.trials
    results = [
        _run_trial(
            contract,
            environment,
            adapter_spec,
            i,
            mode=mode,
            container_network=container_network,
        )
        for i in range(n)
    ]
    verdict = aggregate(results, contract.statistics)
    return RunOutput(verdict=verdict, trials=results)
