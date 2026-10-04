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


def test_precondition_detail_does_not_leak_observed_value(
    trial_db: tuple[ClusterConfig, str],
) -> None:
    # A failing precondition must NOT echo the raw observed DB value into its detail (which the
    # orchestrator folds into the allowlisted trial `reason`). Regression for the §11 leak.
    cfg, db = trial_db
    apply_fixtures(
        cfg.admin_dsn(db),
        [
            "INSERT INTO tenants(id) VALUES ('acme')",
            "INSERT INTO payments(invoice, tenant_id, amount, status, idempotency_key) "
            "VALUES ('ssn-123-45-6789','acme',98.70,'paid','k1')",
        ],
    )
    pc = Precondition(
        description="no sensitive invoice present",
        assert_query="SELECT invoice FROM payments WHERE tenant_id='acme' LIMIT 1",
        assert_equals="expected-benign",  # mismatches the observed 'ssn-123-45-6789'
    )
    results = verify_preconditions(_probe(cfg, db), [pc])
    assert results[0].established is False
    assert "ssn-123-45-6789" not in results[0].detail, "observed DB value leaked into detail"
