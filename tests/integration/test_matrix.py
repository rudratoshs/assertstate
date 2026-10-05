"""`assertstate matrix` runs contracts × adapter targets and gates on the worst verdict
(FEATURE-SPEC §2.4). Requires Postgres (built-in demo env)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from assertstate.cli import main

REPO = Path(__file__).resolve().parents[2]


def _pg() -> bool:
    try:
        return subprocess.run(["pg_isready", "-h", "/tmp"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _pg(), reason="no local Postgres reachable")


def _manifest(targets: list[str]) -> str:
    fh = tempfile.NamedTemporaryFile("w", suffix=".run.yaml", delete=False)
    yaml.safe_dump({"targets": targets, "contracts": ["contracts/pay-invoice.e2e.yaml"]}, fh)
    fh.close()
    return fh.name


def _clean(*rids: str) -> None:
    for rid in rids:
        shutil.rmtree(REPO / ".assertstate" / "runs" / rid, ignore_errors=True)


def test_matrix_single_target_all_pass_is_zero() -> None:
    _clean("pay-invoice.e2e__demo")
    code = main(["matrix", _manifest(["demo"]), "--app", "demo", "--scenario", "correct"])
    assert code == 0  # the one cell (demo adapter) PASSes
    assert (REPO / ".assertstate" / "runs" / "pay-invoice.e2e__demo" / "run.json").exists()


def test_matrix_fans_adapters_and_gates_on_worst() -> None:
    _clean("pay-invoice.e2e__demo", "pay-invoice.e2e__noop")
    # demo adapter satisfies the contract (PASS=0); noop does nothing, so its cell is non-PASS
    # (the contract can't hold) -> the matrix gates on the WORST non-zero code across cells.
    code = main(["matrix", _manifest(["demo", "noop"]), "--app", "demo", "--scenario", "correct"])
    assert code != 0, "a non-PASS cell must gate the matrix non-zero"
    assert code in (1, 3, 4)  # FAIL / INCONCLUSIVE / ERROR-dominated
    # both cells wrote their OWN evidence bundle (one per contract×target)
    assert (REPO / ".assertstate" / "runs" / "pay-invoice.e2e__demo" / "run.json").exists()
    assert (REPO / ".assertstate" / "runs" / "pay-invoice.e2e__noop" / "run.json").exists()
