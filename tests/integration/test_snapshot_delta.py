"""P0-08/P0-09 snapshot + delta against a real Postgres."""

from __future__ import annotations

from assertstate.env.template import ClusterConfig
from assertstate.oracle.db_probe.probe import DbProbe
from assertstate.oracle.delta.engine import diff
from assertstate.oracle.delta.predicate import matches
from assertstate.oracle.snapshot.snapshot import SnapshotQuery, take_snapshot
from tests.integration.conftest import admin_exec


def _probe(cfg: ClusterConfig, db: str) -> DbProbe:
    return DbProbe(cfg.oracle_dsn(db))


def test_snapshot_keys_rows_by_pk(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme');")
    admin_exec(
        cfg,
        db,
        "INSERT INTO payments(invoice, tenant_id, amount, status) "
        "VALUES ('x', 'acme', 1.00, 'paid');",
    )
    snap = take_snapshot(
        _probe(cfg, db),
        [SnapshotQuery("pay", "SELECT id, invoice, tenant_id FROM payments", key="id")],
    )
    qr = snap.queries["pay"]
    assert qr.usable is True
    assert qr.row_count == 1


def test_duplicate_key_makes_snapshot_unusable(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme');")
    admin_exec(
        cfg,
        db,
        "INSERT INTO payments(invoice, tenant_id) VALUES ('x','acme'), ('y','acme');",
    )
    # Keying by tenant_id yields duplicate keys -> unusable (fail-closed).
    snap = take_snapshot(
        _probe(cfg, db),
        [SnapshotQuery("byt", "SELECT tenant_id FROM payments", key="tenant_id")],
    )
    assert snap.queries["byt"].pk_unique is False
    assert snap.usable is False


def test_db_delta_catches_cross_tenant_insert(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme'), ('globex');")
    probe = _probe(cfg, db)
    q = SnapshotQuery("pay", "SELECT id, tenant_id FROM payments WHERE invoice='bill'", key="id")

    admin_exec(
        cfg,
        db,
        "INSERT INTO payments(invoice, tenant_id) VALUES ('bill','acme');",
    )
    before = take_snapshot(probe, [q])

    # A forbidden cross-tenant row is ADDED.
    admin_exec(
        cfg,
        db,
        "INSERT INTO payments(invoice, tenant_id) VALUES ('bill','globex');",
    )
    after = take_snapshot(probe, [q])

    d = diff("pay", before.queries["pay"], after.queries["pay"])
    added_bad = [r for r in d.added.values() if matches("tenant_id != 'acme'", r)]
    assert len(added_bad) == 1  # the forbidden cross-tenant INSERT is caught


def test_db_delta_catches_cross_tenant_update(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme'), ('globex');")
    probe = _probe(cfg, db)
    q = SnapshotQuery("pay", "SELECT id, tenant_id FROM payments WHERE invoice='bill'", key="id")

    admin_exec(cfg, db, "INSERT INTO payments(invoice, tenant_id) VALUES ('bill','acme');")
    before = take_snapshot(probe, [q])

    # An existing acme row is RE-POINTED to another tenant (UPDATE, not INSERT).
    admin_exec(cfg, db, "UPDATE payments SET tenant_id='globex' WHERE invoice='bill';")
    after = take_snapshot(probe, [q])

    d = diff("pay", before.queries["pay"], after.queries["pay"])
    stolen = [
        (b, a)
        for (b, a) in d.changed.values()
        if matches("tenant_id = 'acme'", b) and matches("tenant_id != 'acme'", a)
    ]
    assert len(stolen) == 1  # the cross-tenant UPDATE is caught (added_where alone would miss it)
