"""Every shipped contract validates; the CI workflow is well-formed (P1 seed contracts + CI)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from assertstate.contract.loader import load_and_validate

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = sorted(REPO.glob("contracts/**/*.yaml"))

# Seeds the P1 feature set supports (scenarios 7, 10-12 deferred; see scenarios.md).
EXPECTED_SEEDS = {
    "01-false-success",
    "02-http-200-error",
    "03-wrong-value",
    "04-wrong-tenant",
    "05-duplicate-on-retry",
    "06-unrequested-action",
    "08-external-exfil",
    "09-budget",
}


def test_contracts_are_present() -> None:
    seeds = {p.stem for p in REPO.glob("contracts/seeds/*.yaml")}
    assert seeds == EXPECTED_SEEDS, f"shipped seed set drifted from the documented 8: {seeds}"


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


def test_github_action_is_wellformed() -> None:
    # The reusable composite Action (FEATURE-SPEC §10) that gates a PR on the run verdict.
    action = REPO / "action.yml"
    assert action.exists(), "the composite GitHub Action must ship"
    doc = yaml.safe_load(action.read_text())
    assert doc["runs"]["using"] == "composite"
    for inp in (
        "contract",
        "config",
        "app",
        "scenario",
        "trials",
        "sandbox",
        "run-id",
        "baseline",
        "allow-fork",
        "install",
    ):
        assert inp in doc["inputs"], f"Action must expose the {inp!r} input"
    steps = doc["runs"]["steps"]
    body = " ".join(s.get("run", "") for s in steps)
    uses = " ".join(s.get("uses", "") for s in steps)
    # cross-repo: self-installs from its own source when not importable (no registry/credential)
    assert "GITHUB_ACTION_PATH" in body and "pip install" in body
    assert "assertstate.cli" in body and "run" in body  # runs the trusted CLI, not the agent
    assert "report" in body and "--format summary" in body  # redacted summary via the reporter
    assert "compare" in body  # optional regression gate
    assert "GITHUB_STEP_SUMMARY" in body  # posts a PR summary
    assert "upload-artifact" in uses  # evidence uploaded as an artifact (§6)
    assert "ASSERTSTATE_EXIT" in body  # exit code captured + re-exited (never collapsed)
    # fork fail-closed: refuses a --config (secret) run from a fork unless explicitly allowed
    assert "fork" in body.lower() and "exit 4" in body
    # the gate + summary + artifact must run even on failure
    assert any("always()" in str(s.get("if", "")) for s in steps)


def test_example_workflow_is_wellformed() -> None:
    wf = REPO / ".github" / "workflows" / "assertstate-example.yml"
    assert wf.exists(), "the example consumer workflow must ship"
    doc = yaml.safe_load(wf.read_text())
    assert "assertstate" in doc["jobs"], "stable job name for the required status check"
    assert doc["permissions"]["contents"] == "read"  # least privilege
    steps = doc["jobs"]["assertstate"]["steps"]
    assert any(s.get("uses") == "./" for s in steps)  # invokes the bundled Action
    # the demo path references a REAL contract file
    with_block = next((s.get("with", {}) for s in steps if s.get("uses") == "./"), {})
    assert (REPO / with_block.get("contract", "nope")).exists()
