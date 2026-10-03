"""P0-12 seeding + precondition verification against real Postgres."""

from __future__ import annotations

from assertstate.domain.contract import Precondition
from assertstate.env.seed import (
    apply_fixtures,
    preconditions_established,
    verify_preconditions,
)
from assertstate.env.template import ClusterConfig
from assertstate.oracle.db_probe.probe import DbProbe

PC_ZERO = Precondition(
    description="no payment rows for invoice bill-december",
    assert_query="SELECT count(*) FROM payments WHERE invoice = 'bill-december'",
    assert_equals="0",
)


def _probe(cfg: ClusterConfig, db: str) -> DbProbe:
    return DbProbe(cfg.oracle_dsn(db))


def test_fixtures_apply_and_precondition_holds(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    apply_fixtures(cfg.admin_dsn(db), ["INSERT INTO tenants(id) VALUES ('acme')"])
    results = verify_preconditions(_probe(cfg, db), [PC_ZERO])
    assert preconditions_established(results) is True
    assert results[0].established is True


def test_precondition_fails_when_baseline_not_pinned(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    apply_fixtures(
        cfg.admin_dsn(db),
        [
            "INSERT INTO tenants(id) VALUES ('acme')",
            "INSERT INTO payments(invoice, tenant_id, amount, status, idempotency_key) "
            "VALUES ('bill-december','acme',98.70,'paid','bill-december')",
        ],
    )
    # A pre-existing row means the duplicate baseline (0 rows) is NOT established -> SKIPPED.
    results = verify_preconditions(_probe(cfg, db), [PC_ZERO])
    assert preconditions_established(results) is False


def test_informational_precondition_is_established(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    results = verify_preconditions(_probe(cfg, db), [Precondition(description="just a note")])
    assert preconditions_established(results) is True
