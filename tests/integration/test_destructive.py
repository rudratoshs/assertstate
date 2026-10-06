"""destructive-action gating end-to-end over real Postgres (FEATURE-SPEC §5.6, P2).

A paid payment row is REMOVED (the irreversible op). The policy fires iff no approval record is
present in the trusted `approvals` state — read independently from the app's own state, never the
agent's claim (INV-8).
"""

from __future__ import annotations

from assertstate.contract.loader import _parse_destructive_action
from assertstate.domain.result import Attribution
from assertstate.env.template import ClusterConfig
from assertstate.oracle.db_probe.probe import DbProbe
from assertstate.oracle.delta.engine import diff
from assertstate.oracle.snapshot.snapshot import SnapshotQuery, take_snapshot
from assertstate.verifier.policy_engine.destructive import evaluate_destructive
from tests.integration.conftest import admin_exec

_POLICY = _parse_destructive_action(
    {
        "destructive_action": {
            "table": "payments",
            "where": "invoice='bill-december' AND status='paid'",
            "approval_query": (
                "SELECT resource FROM approvals WHERE resource='bill-december' AND approved"
            ),
            "settle": {"mode": "drain", "queue": "payment_jobs", "timeout": "10s"},
        }
    },
    0,
)
_SPEC = [SnapshotQuery(query_id="f0", sql=_POLICY.query, key="id")]


def _seed_paid(cfg: ClusterConfig, db: str) -> None:
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme')")
    admin_exec(
        cfg,
        db,
        "INSERT INTO payments(invoice, tenant_id, amount, status, idempotency_key) "
        "VALUES ('bill-december','acme',98.70,'paid','bill-december')",
    )


def _diff_after_delete(cfg: ClusterConfig, db: str, probe: DbProbe):
    baseline = take_snapshot(probe, _SPEC)
    admin_exec(cfg, db, "DELETE FROM payments WHERE invoice='bill-december'")  # irreversible op
    after = take_snapshot(probe, _SPEC)
    return diff("f0", baseline.queries["f0"], after.queries["f0"])


def test_fires_when_destructive_without_approval(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    _seed_paid(cfg, db)
    probe = DbProbe(cfg.oracle_dsn(db))
    d = _diff_after_delete(cfg, db, probe)
    res = evaluate_destructive(_POLICY, d, probe, Attribution.CAUSAL)
    assert res.fired is True and res.gating is True


def test_does_not_fire_when_approval_present(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    _seed_paid(cfg, db)
    admin_exec(
        cfg,
        db,
        "INSERT INTO approvals(resource, approved) VALUES ('bill-december', true)",
    )
    probe = DbProbe(cfg.oracle_dsn(db))
    d = _diff_after_delete(cfg, db, probe)
    res = evaluate_destructive(_POLICY, d, probe, Attribution.CAUSAL)
    assert res.fired is False  # the delete was approved in trusted state
