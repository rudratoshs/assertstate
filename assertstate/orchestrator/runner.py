"""Run orchestrator — the canonical per-trial lifecycle (SYSTEM-DESIGN §5; DEVELOPMENT §9).

isolate -> seed/preconditions -> baseline -> act(adapter, out-of-process) -> settle(drain)
-> after -> verify(expect + db_delta) -> record -> aggregate.

The verdict is computed only from the oracle + settled deltas; AgentTrace.agent_claimed_done
is recorded as evidence and never gates (INV-8). Any inability to establish correctness
(snapshot unusable, oracle/adapter/settlement failure) is ERROR, never FAIL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from assertstate.adapters.base import AdapterError
from assertstate.adapters.runner import run_adapter
from assertstate.domain.contract import Contract, DbDeltaPolicy
from assertstate.domain.result import Attribution, Outcome, SettlementRecord, TrialResult
from assertstate.domain.snapshot import Snapshot
from assertstate.domain.trace import AgentTrace, BrowserObservations
from assertstate.domain.verdict import RunVerdict
from assertstate.env.seed import preconditions_established, verify_preconditions
from assertstate.instrumentation.observations import observations_from_capture
from assertstate.oracle.db_probe.probe import DbProbe, OracleError
from assertstate.oracle.delta.engine import DeltaError, diff
from assertstate.oracle.delta.predicate import PredicateError
from assertstate.oracle.settlement.controller import SettlementController, SettlementError
from assertstate.oracle.settlement.queue import QueueProbe
from assertstate.oracle.snapshot.snapshot import SnapshotQuery, take_snapshot
from assertstate.orchestrator.environment import Environment, TrialContext
from assertstate.stats.aggregate import aggregate
from assertstate.verifier.expect.comparators import ComparatorError
from assertstate.verifier.expect.evaluator import evaluate_db_expect
from assertstate.verifier.policy_engine.db_delta import evaluate_db_delta


@dataclass
class RunOutput:
    verdict: RunVerdict
    trials: list[TrialResult]


def _delta_specs(contract: Contract) -> list[SnapshotQuery]:
    specs = []
    for idx, policy in enumerate(contract.forbid):
        specs.append(SnapshotQuery(query_id=f"f{idx}", sql=policy.query, key=policy.key or "id"))
    return specs


def _settle(contract: Contract, probe: DbProbe, ctx: TrialContext) -> SettlementRecord | None:
    """Dispatch the contract's settlement. One settlement per trial (one after-snapshot).

    All-`bounded` -> bounded (needs the trusted capture anchor). Otherwise, if any policy
    requires `drain`, drain (the stronger server-side guarantee). No forbid -> no settle.
    """
    modes = {p.settle.mode for p in contract.forbid}
    if not modes:
        return None

    if modes == {"bounded"}:
        max_wait = max((p.settle.max_wait_s or 0.0) for p in contract.forbid)
        if ctx.capture is not None:
            observations = observations_from_capture(ctx.capture)
        else:
            observations = BrowserObservations()  # no instrumentation -> anchor None -> ERROR
        return SettlementController().bounded(observations, max_wait_s=max_wait)

    drains: list[DbDeltaPolicy] = [p for p in contract.forbid if p.settle.mode == "drain"]
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
) -> tuple[Outcome, str, list[dict[str, Any]], list[dict[str, Any]]]:
    expect_results: list[dict[str, Any]] = []
    expect_ok = True
    for e in contract.expect:
        r = evaluate_db_expect(probe, e)
        expect_results.append({"query": r.query, "ok": r.ok, "detail": r.detail})
        expect_ok = expect_ok and r.ok

    policy_results: list[dict[str, Any]] = []
    gating_fired = False
    for idx, policy in enumerate(contract.forbid):
        qid = f"f{idx}"
        d = diff(qid, baseline.queries[qid], after.queries[qid])
        pr = evaluate_db_delta(policy, d, attribution)
        policy_results.append(
            {"query_id": qid, "fired": pr.fired, "gating": pr.gating, "detail": pr.detail}
        )
        if pr.fired and pr.gating:  # observed (shared-staging) deltas are non-gating (§6.5)
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
    contract: Contract, environment: Environment, adapter_spec: str, index: int
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
            timeout_s=timeout_s + 10.0,
            extra_env=ctx.adapter_env or None,  # agent-side creds only; oracle DSN never here
        )

        settlement = _settle(contract, probe, ctx)

        after = take_snapshot(probe, specs)
        if not after.usable:
            return TrialResult(outcome=Outcome.ERROR, reason="after snapshot unusable")

        attribution = ctx.attribution
        outcome, reason, expect_results, policy_results = _verify(
            contract, baseline, after, probe, attribution
        )
        return TrialResult(
            outcome=outcome,
            reason=reason,
            attribution=attribution,
            expect_results=tuple(expect_results),
            policy_results=tuple(policy_results),
            settlement=settlement,
            refs={"agent_claimed_done": str(trace.agent_claimed_done)},  # recorded, NOT trusted
        )
    except SettlementError as exc:
        return TrialResult(outcome=Outcome.ERROR, reason=f"settlement: {exc}")
    except AdapterError as exc:
        return TrialResult(outcome=Outcome.ERROR, reason=f"adapter: {exc}")
    except (OracleError, DeltaError, PredicateError, ComparatorError) as exc:
        return TrialResult(outcome=Outcome.ERROR, reason=f"{type(exc).__name__}: {exc}")
    finally:
        if ctx is not None:
            environment.teardown(ctx)


def run_contract(
    contract: Contract,
    environment: Environment,
    adapter_spec: str,
    *,
    trials: int | None = None,
) -> RunOutput:
    n = trials if trials is not None else contract.statistics.trials
    results = [_run_trial(contract, environment, adapter_spec, i) for i in range(n)]
    verdict = aggregate(results, contract.statistics)
    return RunOutput(verdict=verdict, trials=results)
