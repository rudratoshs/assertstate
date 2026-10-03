"""Integration fixtures for the DB/oracle spine (P0-06..P0-09).

Skips the whole integration suite when no local Postgres is reachable, so the unit
tier still runs anywhere. Builds the demo template once per session and hands each
test a fresh disposable trial DB (template restore), dropped afterwards.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import uuid
from collections.abc import Iterator
from types import ModuleType

import pytest

from assertstate.env.template import (
    ClusterConfig,
    TemplateError,
    build_template,
    create_trial_db,
    drop_db,
)

CFG = ClusterConfig()


def _pg_available(cfg: ClusterConfig) -> bool:
    try:
        return subprocess.run(["pg_isready", "-h", cfg.host], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


@pytest.fixture(scope="session")
def cluster() -> ClusterConfig:
    if not _pg_available(CFG):
        pytest.skip("no local Postgres reachable")
    try:
        build_template(CFG)
    except TemplateError as exc:
        pytest.skip(f"cannot build demo template: {exc}")
    return CFG


@pytest.fixture
def trial_db(cluster: ClusterConfig) -> Iterator[tuple[ClusterConfig, str]]:
    name = f"assertstate_test_{uuid.uuid4().hex[:12]}"
    create_trial_db(cluster, name)
    try:
        yield cluster, name
    finally:
        drop_db(cluster, name)


def admin_exec(cfg: ClusterConfig, db: str, sql: str) -> None:
    """Run DDL/DML as the superuser/migrator (test seeding helper)."""
    import psycopg

    with psycopg.connect(cfg.admin_dsn(db), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql)  # type: ignore[arg-type]


def load_demo_worker() -> ModuleType:
    """Import demo-app/worker.py (hyphenated dir is not a normal package)."""
    path = pathlib.Path(__file__).resolve().parents[2] / "demo-app" / "worker.py"
    spec = importlib.util.spec_from_file_location("demo_worker", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
