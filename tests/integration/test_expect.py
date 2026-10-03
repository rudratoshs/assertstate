"""P0-16 expect.db evaluator against real Postgres."""

from __future__ import annotations

from assertstate.domain.comparator import Comparator
from assertstate.domain.contract import DbExpect, Eventually
from assertstate.env.template import ClusterConfig
from assertstate.oracle.db_probe.probe import DbProbe
from assertstate.verifier.expect.evaluator import evaluate_db_expect
from tests.integration.conftest import admin_exec

SEED = """
INSERT INTO tenants(id) VALUES ('acme');
INSERT INTO payments(invoice, tenant_id, amount, status, idempotency_key)
VALUES ('bill-december','acme',98.70,'paid','bill-december');
"""


def _probe(cfg: ClusterConfig, db: str) -> DbProbe:
    return DbProbe(cfg.oracle_dsn(db))


def test_status_equals_paid(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, SEED)
    e = DbExpect(
        query="SELECT status FROM payments WHERE invoice='bill-december'",
        comparator=Comparator.EQUALS,
        value="paid",
    )
    assert evaluate_db_expect(_probe(cfg, db), e).ok is True


def test_amount_eq_canonical_numeric(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, SEED)
    # DB stores numeric(12,2) -> Decimal('98.70'); contract says "98.70" (and "98.7" also matches).
    e = DbExpect(
        query="SELECT amount FROM payments WHERE invoice='bill-december'",
        comparator=Comparator.EQ_CANONICAL,
        value="98.7",
    )
    assert evaluate_db_expect(_probe(cfg, db), e).ok is True


def test_wrong_amount_fails(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, SEED)
    e = DbExpect(
        query="SELECT amount FROM payments WHERE invoice='bill-december'",
        comparator=Comparator.EQ_CANONICAL,
        value="9.87",
    )
    r = evaluate_db_expect(_probe(cfg, db), e)
    assert r.ok is False and r.present is True


def test_missing_row_fails_not_errors(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme')")  # no payment
    e = DbExpect(
        query="SELECT status FROM payments WHERE invoice='nope'",
        comparator=Comparator.EQUALS,
        value="paid",
    )
    r = evaluate_db_expect(_probe(cfg, db), e)
    assert r.ok is False and r.present is False


def test_absent_when_no_row(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme')")
    e = DbExpect(
        query="SELECT id FROM payments WHERE invoice='nope'",
        comparator=Comparator.ABSENT,
        value=None,
    )
    assert evaluate_db_expect(_probe(cfg, db), e).ok is True


def test_eventually_gives_up_and_reports_last(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme')")
    e = DbExpect(
        query="SELECT status FROM payments WHERE invoice='never'",
        comparator=Comparator.EQUALS,
        value="paid",
        eventually=Eventually(timeout_ms=150, poll_ms=50),
    )
    assert evaluate_db_expect(_probe(cfg, db), e).ok is False  # polled, still absent
