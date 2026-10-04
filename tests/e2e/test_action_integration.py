"""Executes the GitHub Action's integration PATH through the real CLI (not a mocked engine):
run -> `report --format summary` -> the evidence dir upload-artifact would grab -> gate exit.

The only thing NOT exercised here is GitHub's own YAML/runner wiring (action.yml well-formedness
is covered separately). Requires local Postgres; skips otherwise."""

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


def _clean(run_id: str) -> None:
    import shutil

    shutil.rmtree(REPO / ".assertstate" / "runs" / run_id, ignore_errors=True)


def _summary_to(run_id: str, path: Path, capsys: pytest.CaptureFixture[str]) -> str:
    # The Action does: `report --format summary >> $GITHUB_STEP_SUMMARY`.
    assert main(["report", run_id, "--format", "summary"]) == 0
    out = capsys.readouterr().out
    path.write_text(out, encoding="utf-8")
    return out


def test_action_path_fail_gates_and_summarizes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rid = "act-fail"
    _clean(rid)
    # Step 1 — run (the Action captures this exit code, never silently passes).
    code = main(["run", CONTRACT, "--app", "demo", "--scenario", "slow_retry", "--run-id", rid])
    assert code == 1  # FAIL -> the gate step re-exits 1 -> PR check fails
    # Step 2 — redacted summary (what goes into $GITHUB_STEP_SUMMARY).
    summary = _summary_to(rid, tmp_path / "step_summary.md", capsys)
    assert "Verdict: **FAIL**" in summary
    assert "authoritative application-state contract FAILED" in summary
    for leak in ("postgres://", "dbname=", "password=", "://"):
        assert leak not in summary.lower(), f"summary leaked {leak!r}"
    # Step 3 — the evidence dir upload-artifact would grab exists with the expected files.
    run_dir = REPO / ".assertstate" / "runs" / rid
    for f in (
        "run.json",
        "manifest.json",
        "evidence.zip",
        "contract.yaml",
        "junit.xml",
        "report.html",
    ):
        assert (run_dir / f).exists(), f"evidence artifact missing {f}"
    assert (run_dir / "trials").is_dir()


def test_action_path_pass_gates_zero(capsys: pytest.CaptureFixture[str]) -> None:
    rid = "act-pass"
    _clean(rid)
    code = main(["run", CONTRACT, "--app", "demo", "--scenario", "correct", "--run-id", rid])
    assert code == 0  # PASS -> gate re-exits 0 -> PR check passes
    assert main(["report", rid, "--format", "summary"]) == 0
    assert "Verdict: **PASS**" in capsys.readouterr().out
