"""Every shipped contract validates; the CI workflow is well-formed (P1 seed contracts + CI)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from assertstate.contract.loader import load_and_validate

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = sorted(REPO.glob("contracts/**/*.yaml"))


def test_contracts_are_present() -> None:
    assert len(CONTRACTS) >= 8, "expected the example + seed contracts to ship"


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda p: p.name)
def test_shipped_contract_validates(path: Path) -> None:
    contract, report = load_and_validate(path)
    assert report.ok, f"{path.name}: {report.errors}"
    assert contract is not None


def test_ci_workflow_is_wellformed() -> None:
    wf = REPO / ".github" / "workflows" / "ci.yml"
    assert wf.exists(), "CI workflow must exist"
    doc = yaml.safe_load(wf.read_text())
    steps = doc["jobs"]["test"]["steps"]
    run_cmds = " ".join(s.get("run", "") for s in steps)
    assert "ruff check" in run_cmds
    assert "mypy" in run_cmds
    assert "pytest" in run_cmds
    # integration runs against a postgres service in CI
    assert "postgres" in doc["jobs"]["test"]["services"]
