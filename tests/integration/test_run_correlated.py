"""run_correlated settlement end-to-end over real Postgres (FEATURE-SPEC §5a, P2).

Proves the UNIQUE value of run-correlation: the delta is filtered to THIS run's rows, so a
CONCURRENT other run's writes are excluded with no temporal inference. An unfiltered temporal diff
would false-positive on the concurrent run; the run_id filter does not.
"""

from __future__ import annotations

import threading

from assertstate.domain.contract import DbDeltaPolicy, SettlementConfig
from assertstate.domain.result import Attribution
from assertstate.env.template import ClusterConfig
from assertstate.oracle.db_probe.probe import DbProbe
from assertstate.oracle.delta.engine import diff
from assertstate.oracle.settlement.controller import SettlementController
from assertstate.oracle.settlement.queue import QueueProbe
from assertstate.oracle.snapshot.snapshot import SnapshotQuery, take_snapshot
from assertstate.orchestrator.runner import _filter_delta_by_run_id
from assertstate.verifier.policy_engine.db_delta import evaluate_db_delta
from tests.integration.conftest import admin_exec, load_demo_worker

_Q = "SELECT id, run_id FROM payments WHERE invoice='bill-december'"
_SPEC = [SnapshotQuery(query_id="f0", sql=_Q, key="id")]


def _pay(cfg: ClusterConfig, db: str, run_id: str) -> None:
    admin_exec(
        cfg,
        db,
        "INSERT INTO payments(invoice, tenant_id, amount, status, idempotency_key, run_id) "
        f"VALUES ('bill-december','acme',98.70,'paid','bill-december','{run_id}')",
    )


def _policy() -> DbDeltaPolicy:
    return DbDeltaPolicy(
        query=_Q,
        settle=SettlementConfig(mode="run_correlated", run_id_col="run_id", queue="payment_jobs"),
        max_added=1,
    )


def test_run_correlated_excludes_a_concurrent_run(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme')")
    probe = DbProbe(cfg.oracle_dsn(db))

    baseline = take_snapshot(probe, _SPEC)  # no payments yet
    # THIS run (runA) writes a duplicate; a CONCURRENT run (runB) writes one legitimate row.
    _pay(cfg, db, "runA")
    _pay(cfg, db, "runA")
    _pay(cfg, db, "runB")
    after = take_snapshot(probe, _SPEC)

    raw = diff("f0", baseline.queries["f0"], after.queries["f0"])
    # Unfiltered temporal diff sees ALL 3 added rows -> would wrongly blame runA for runB's write.
    assert len(raw.added) == 3

    filtered = _filter_delta_by_run_id(raw, "run_id", "runA")
    assert len(filtered.added) == 2  # only runA's rows; runB excluded

    res = evaluate_db_delta(_policy(), filtered, Attribution.CAUSAL)
    assert res.fired is True and res.gating is True  # 2 added > max_added 1 -> duplicate caught


def test_run_correlated_passes_single_run_despite_concurrency(
    trial_db: tuple[ClusterConfig, str],
) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme')")
    probe = DbProbe(cfg.oracle_dsn(db))

    baseline = take_snapshot(probe, _SPEC)
    _pay(cfg, db, "runA")  # this run: exactly one
    _pay(cfg, db, "runB")  # concurrent other run
    after = take_snapshot(probe, _SPEC)

    filtered = _filter_delta_by_run_id(
        diff("f0", baseline.queries["f0"], after.queries["f0"]), "run_id", "runA"
    )
    res = evaluate_db_delta(_policy(), filtered, Attribution.CAUSAL)
    assert res.fired is False  # runA added exactly one; runB's write does not count against it


def test_run_correlated_awaits_completion_then_catches_late_duplicate(
    trial_db: tuple[ClusterConfig, str],
) -> None:
    # End-to-end: the controller proves completion by draining the queue (so a SLOW retry duplicate
    # committed AFTER a naive snapshot is not missed), then the delta is filtered to THIS run — a
    # concurrently-inserted other run's row is excluded. Catches the late write; ignores the peer.
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme')")
    worker = load_demo_worker().DemoWorker(cfg.admin_dsn(db))
    probe = DbProbe(cfg.oracle_dsn(db))
    run_id = "run-A"

    baseline = take_snapshot(probe, _SPEC)
    t = threading.Thread(target=worker.run_forever, args=(run_id, 0.02), daemon=True)
    t.start()
    try:
        worker.enqueue(run_id, "bill-december", process_after_s=0.0)  # the payment
        worker.enqueue(run_id, "bill-december", process_after_s=0.5)  # SLOW retry -> duplicate
        worker.close_producers(run_id)
        # A concurrent OTHER run writes its own legitimate row while we settle.
        _pay(cfg, db, "run-B")
        # run_correlated completion == drain (waits past the 0.5s retry) -> late duplicate lands.
        rec = SettlementController().run_correlated(QueueProbe(probe), run_id, timeout_s=5.0)
        assert rec.mode == "run_correlated"
    finally:
        worker.stop()
        t.join(timeout=3)

    after = take_snapshot(probe, _SPEC)
    raw = diff("f0", baseline.queries["f0"], after.queries["f0"])
    filtered = _filter_delta_by_run_id(raw, "run_id", run_id)
    assert len(filtered.added) == 2  # both run-A payments (incl. the late retry); run-B excluded
    res = evaluate_db_delta(_policy(), filtered, Attribution.CAUSAL)
    assert res.fired is True  # the late duplicate is caught
