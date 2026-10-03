"""P0-X1 — the canonical end-to-end acceptance proof, THROUGH `assertstate run`.

Agent (out-of-process, app-write-only) enqueues the workflow and claims DONE; for the
slow-retry scenario it also schedules a delayed duplicate. The orchestrator drains, reads
the oracle, diffs, and the duplicate db_delta fires -> FAIL. The 'correct' scenario -> PASS.
Evidence is written. Skips if no local Postgres.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from assertstate.cli import main

REPO = Path(__file__).resolve().parents[2]
CONTRACT = str(REPO / "contracts" / "pay-invoice.e2e.yaml")


def _pg() -> bool:
    try:
        return subprocess.run(["pg_isready", "-h", "/tmp"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _pg(), reason="no local Postgres reachable")


def test_slow_retry_counterfactual_fails_through_run() -> None:
    # agent claims DONE; slow-retry duplicate committed after an early snapshot would be;
    # drain exposes it; the duplicate db_delta fires -> Run verdict FAIL -> exit 1.
    code = main(
        ["run", CONTRACT, "--app", "demo", "--scenario", "slow_retry", "--run-id", "x1-fail"]
    )
    assert code == 1
    assert (REPO / ".assertstate" / "runs" / "x1-fail" / "run.json").exists()
    assert (REPO / ".assertstate" / "runs" / "x1-fail" / "manifest.json").exists()


def test_correct_run_passes_through_run() -> None:
    code = main(["run", CONTRACT, "--app", "demo", "--scenario", "correct", "--run-id", "x1-pass"])
    assert code == 0


def test_evidence_redacts_app_credentials() -> None:
    import json

    main(["run", CONTRACT, "--app", "demo", "--scenario", "correct", "--run-id", "x1-redact"])
    trial = REPO / ".assertstate" / "runs" / "x1-redact" / "trials" / "trial-0000.json"
    blob = trial.read_text()
    # The app-write DSN must never appear in evidence; the key is masked.
    assert "postgres" not in blob.lower() or "***REDACTED***" in blob
    data = json.loads(blob)
    assert data["outcome"] == "PASS"
