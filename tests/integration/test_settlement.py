"""P0-10 worker + P0-11 drain controller against real Postgres.

The headline test proves WHY drain exists: a slow-retry duplicate is committed AFTER an
early snapshot would be taken, so a naive after-snapshot misses it (would false-PASS),
while a drained after-snapshot sees it (the duplicate is caught).
"""

from __future__ import annotations

import threading

from assertstate.env.template import ClusterConfig
from assertstate.oracle.db_probe.probe import DbProbe
from assertstate.oracle.delta.engine import diff
from assertstate.oracle.settlement.controller import SettlementController, SettlementError
from assertstate.oracle.settlement.queue import QueueProbe
from assertstate.oracle.snapshot.snapshot import SnapshotQuery, take_snapshot
from tests.integration.conftest import admin_exec, load_demo_worker

DUPE_Q = SnapshotQuery("dupe", "SELECT id FROM payments WHERE invoice='bill'", key="id")


def _probe(cfg: ClusterConfig, db: str) -> DbProbe:
    return DbProbe(cfg.oracle_dsn(db))


def test_drain_waits_for_slow_retry_and_exposes_the_duplicate(
    trial_db: tuple[ClusterConfig, str],
) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme'),('globex')")
    worker_mod = load_demo_worker()
    worker = worker_mod.DemoWorker(cfg.admin_dsn(db))  # app-side writer
    run_id = "run-1"

    probe = _probe(cfg, db)
    before = take_snapshot(probe, [DUPE_Q]).queries["dupe"]
    assert before.row_count == 0  # baseline pinned to 0 (FEATURE-SPEC §5.2)

    t = threading.Thread(target=worker.run_forever, args=(run_id, 0.02), daemon=True)
    t.start()
    try:
        worker.enqueue(run_id, "bill", process_after_s=0.0)  # the payment
        worker.enqueue(run_id, "bill", process_after_s=0.5)  # the SLOW RETRY -> duplicate
        worker.close_producers(run_id)

        # NAIVE after-snapshot (no settlement): taken immediately, within the 0.5s window,
        # so the slow-retry duplicate cannot be visible yet -> a naive check would PASS.
        naive = take_snapshot(probe, [DUPE_Q]).queries["dupe"]
        assert naive.row_count <= 1

        # DRAINED after-snapshot: wait until producers closed AND queue empty.
        result = SettlementController().drain(QueueProbe(probe), run_id, timeout_s=5.0, poll_s=0.02)
        drained = take_snapshot(probe, [DUPE_Q]).queries["dupe"]
    finally:
        worker.stop()
        t.join(timeout=2)

    assert result.state.queued == 0 and result.state.active == 0
    assert result.state.producers_closed is True
    assert result.waited_s >= 0.4  # drain genuinely waited for the delayed retry

    # Post-drain the duplicate IS present; the db_delta catches the false success.
    d = diff("dupe", before, drained)
    assert len(d.added) == 2
    assert len(d.added) > 1  # max_added:1 is violated -> FAIL (the duplicate drain exposed)


def test_drain_times_out_to_error_when_producers_never_close(
    trial_db: tuple[ClusterConfig, str],
) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme')")
    worker = load_demo_worker().DemoWorker(cfg.admin_dsn(db))
    run_id = "run-open"
    worker.enqueue(run_id, "bill", process_after_s=0.0)
    # producers NOT closed -> drain can never be proven -> ERROR (never FAIL).
    import pytest

    with pytest.raises(SettlementError):
        SettlementController().drain(
            QueueProbe(_probe(cfg, db)), run_id, timeout_s=0.5, poll_s=0.05
        )


def test_drain_succeeds_cleanly_for_a_correct_run(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme')")
    worker = load_demo_worker().DemoWorker(cfg.admin_dsn(db))
    run_id = "run-ok"
    t = threading.Thread(target=worker.run_forever, args=(run_id, 0.02), daemon=True)
    t.start()
    try:
        worker.enqueue(run_id, "bill", process_after_s=0.0)
        worker.close_producers(run_id)
        result = SettlementController().drain(
            QueueProbe(_probe(cfg, db)), run_id, timeout_s=5.0, poll_s=0.02
        )
        final = take_snapshot(_probe(cfg, db), [DUPE_Q]).queries["dupe"]
    finally:
        worker.stop()
        t.join(timeout=2)
    assert result.state.last_processed_job is not None
    assert final.row_count == 1  # exactly one payment, no duplicate
