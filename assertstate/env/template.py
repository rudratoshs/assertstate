"""P0 environment: demo template build + per-trial disposable DBs (DEVELOPMENT.md §19, §20).

P0 isolation strategy is template/snapshot restore: a template DB is built once
(schema + grants), then each trial gets a fresh ``CREATE DATABASE ... TEMPLATE`` copy,
dropped afterwards. DDL/grants are applied with ``psql`` (native multi-statement + :vars);
programmatic probing uses psycopg (see oracle/db_probe).
"""

from __future__ import annotations

import getpass
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo-app"
SCHEMA_SQL = DEMO_DIR / "schema.sql"
GRANTS_SQL = DEMO_DIR / "grants.sql"


def _default_host() -> str:
    return os.environ.get("ASSERTSTATE_PG_HOST", "/tmp")


def _default_admin_user() -> str:
    # Env-driven, never a hardcoded developer name. Falls back to the OS user, which is
    # the usual local superuser on a fresh Homebrew/initdb cluster (reproducible).
    return os.environ.get("ASSERTSTATE_PG_ADMIN_USER") or getpass.getuser()


@dataclass(frozen=True)
class ClusterConfig:
    """How to reach the local Postgres cluster for P0 (DEVELOPMENT.md §5).

    No machine-specific values are baked in: host/admin come from env (ASSERTSTATE_PG_HOST,
    ASSERTSTATE_PG_ADMIN_USER) or the OS user, so the template builds on a clean instance.
    """

    host: str = field(default_factory=_default_host)
    admin_user: str = field(default_factory=_default_admin_user)
    oracle_role: str = "assertstate_oracle_ro"
    template_db: str = "assertstate_demo_template"
    maintenance_db: str = "postgres"

    def admin_dsn(self, db: str) -> str:
        return f"host={self.host} dbname={db} user={self.admin_user}"

    def oracle_dsn(self, db: str) -> str:
        """DSN for the READ-ONLY oracle role against ``db`` (never carries write privilege)."""
        return f"host={self.host} dbname={db} user={self.oracle_role}"


class TemplateError(RuntimeError):
    """Raised when the demo template/trial DB cannot be built or torn down."""


def _psql(cfg: ClusterConfig, db: str, *args: str) -> None:
    cmd = ["psql", "-v", "ON_ERROR_STOP=1", "-h", cfg.host, "-U", cfg.admin_user, "-d", db, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise TemplateError(f"psql failed ({' '.join(args)}): {proc.stderr.strip()}")


def ensure_oracle_role(cfg: ClusterConfig) -> None:
    """Create the read-only login role if absent (cluster-global, idempotent)."""
    do_block = (
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{cfg.oracle_role}') THEN "
        f"CREATE ROLE {cfg.oracle_role} LOGIN; END IF; END $$;"
    )
    _psql(cfg, cfg.maintenance_db, "-c", do_block)


def build_template(cfg: ClusterConfig) -> None:
    """(Re)build the demo template DB: drop, create, apply schema, apply grants."""
    ensure_oracle_role(cfg)
    _psql(cfg, cfg.maintenance_db, "-c", f'DROP DATABASE IF EXISTS "{cfg.template_db}";')
    _psql(cfg, cfg.maintenance_db, "-c", f'CREATE DATABASE "{cfg.template_db}";')
    _psql(cfg, cfg.template_db, "-f", str(SCHEMA_SQL))
    _psql(
        cfg,
        cfg.template_db,
        "-v",
        f"db_name={cfg.template_db}",
        "-v",
        f"oracle_role={cfg.oracle_role}",
        "-f",
        str(GRANTS_SQL),
    )


def create_trial_db(cfg: ClusterConfig, trial_db: str) -> None:
    """Create a fresh per-trial DB from the template (DEVELOPMENT.md §20)."""
    _psql(
        cfg,
        cfg.maintenance_db,
        "-c",
        f'CREATE DATABASE "{trial_db}" TEMPLATE "{cfg.template_db}";',
    )


def drop_db(cfg: ClusterConfig, db: str) -> None:
    """Drop a DB (terminating other connections first), tolerating absence."""
    _psql(
        cfg,
        cfg.maintenance_db,
        "-c",
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{db}' AND pid <> pg_backend_pid();",
    )
    _psql(cfg, cfg.maintenance_db, "-c", f'DROP DATABASE IF EXISTS "{db}";')
