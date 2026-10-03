"""P0-07 read-only oracle probe against a real Postgres (DEVELOPMENT.md §13)."""

from __future__ import annotations

import pytest

from assertstate.env.template import ClusterConfig
from assertstate.oracle.db_probe.probe import DbProbe, OracleError
from tests.integration.conftest import admin_exec

SEED = """
INSERT INTO tenants(id) VALUES ('acme'), ('globex');
INSERT INTO payments(invoice, tenant_id, amount, status) VALUES
  ('bill-a', 'acme', 10.00, 'paid'),
  ('bill-b', 'acme', 20.00, 'paid'),
  ('bill-c', 'globex', 30.00, 'pending');
"""


def _ro_probe(cfg: ClusterConfig, db: str) -> DbProbe:
    return DbProbe(cfg.oracle_dsn(db))


def test_read_only_role_passes_the_privilege_probe(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    _ro_probe(cfg, db).verify_read_only()  # must NOT raise


def test_superuser_probe_is_detected_as_writable(trial_db: tuple[ClusterConfig, str]) -> None:
    # The probe must actually DETECT a writable role, not merely always-pass.
    cfg, db = trial_db
    writable = DbProbe(cfg.admin_dsn(db))
    with pytest.raises(OracleError, match="read-only check FAILED"):
        writable.verify_read_only()


def test_select_returns_rows(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, SEED)
    res = _ro_probe(cfg, db).select("SELECT invoice, tenant_id FROM payments ORDER BY invoice")
    assert res.truncated is False
    assert [r["invoice"] for r in res.rows] == ["bill-a", "bill-b", "bill-c"]


def test_cardinality_cap_detects_truncation(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, SEED)
    res = _ro_probe(cfg, db).select("SELECT invoice FROM payments", cap=2)
    assert res.truncated is True
    assert len(res.rows) == 2


def test_missing_table_is_error(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    with pytest.raises(OracleError):
        _ro_probe(cfg, db).select("SELECT * FROM does_not_exist")


def test_oracle_cannot_select_the_sentinel(trial_db: tuple[ClusterConfig, str]) -> None:
    # No grant on the sentinel table at all -> even SELECT is denied -> ERROR, never silent.
    cfg, db = trial_db
    with pytest.raises(OracleError):
        _ro_probe(cfg, db).select("SELECT id FROM assertstate_readonly_probe")
