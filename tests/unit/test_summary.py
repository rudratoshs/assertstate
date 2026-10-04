"""GitHub step-summary reporter + `assertstate report --format summary` (FEATURE-SPEC §5, §10).

Verifies the summary carries the verdict/trial stats, flags FAIL as an authoritative-state
failure, renders INCONCLUSIVE/None safely, and leaks NO secrets (it only reads redacted verdict
scalars — a secret planted in a per-trial detail must not appear)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assertstate.cli import main
from assertstate.domain.metadata import RunMetadata
from assertstate.domain.result import Outcome, TrialResult
from assertstate.domain.verdict import RunOutcome, RunVerdict
from assertstate.evidence.bundle import write_run
from assertstate.reporters.summary import to_step_summary


def _data(verdict: str = "PASS", wilson: float | None = 0.88, reason: str = "ok") -> dict:
    return {
        "run_id": "r1",
        "verdict": {
            "verdict": verdict,
            "total_trials": 30,
            "valid_trials": 30,
            "passed": 28,
            "failed": 2,
            "errored": 0,
            "skipped": 0,
            "wilson_lower": wilson,
            "confidence": 0.95,
            "side": "one_sided",
            "pass_threshold": 0.85,
            "error_rate": 0.0,
            "skip_rate": 0.0,
            "reason": reason,
        },
        "metadata": {"adapter_name": "demo", "scenario_id": "correct", "contract_hash": "abc"},
        "scope": {"establishes": "E", "does_not_establish": "N"},
    }


def test_summary_has_verdict_and_stats() -> None:
    s = to_step_summary(_data("PASS"))
    assert "## AssertState" in s
    assert "Verdict: **PASS**" in s
    assert "PASS | FAIL | ERROR | SKIPPED" in s and "| 28 | 2 | 0 | 0 |" in s
    assert "Wilson lower bound:" in s and "0.88" in s
    assert "Completeness:" in s and "Evidence:" in s


def test_summary_flags_fail_as_authoritative_state_failure() -> None:
    s = to_step_summary(_data("FAIL"))
    assert "authoritative application-state contract FAILED" in s


def test_summary_renders_inconclusive_without_crashing() -> None:
    s = to_step_summary(_data("INCONCLUSIVE", wilson=None))
    assert "Verdict: **INCONCLUSIVE**" in s
    assert "n/a" in s  # None wilson rendered safely


def test_summary_leaks_no_secret_from_trial_detail() -> None:
    d = _data("FAIL")
    # A secret ONLY in a per-trial detail must never surface — the summary reads verdict scalars.
    d["verdict"]["per_trial"] = [{"detail": "dsn=postgres://u:SECRET@h/db"}]
    s = to_step_summary(d)
    assert "SECRET" not in s and "postgres://" not in s


def test_report_summary_through_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    v = RunVerdict(
        verdict=RunOutcome.FAIL,
        total_trials=3,
        valid_trials=3,
        passed=0,
        failed=3,
        errored=0,
        skipped=0,
        pass_rate=0.0,
        wilson_lower=0.0,
        confidence=0.95,
        side="one_sided",
        pass_threshold=0.5,
        error_rate=0.0,
        skip_rate=0.0,
        reason="expect_ok=True gating_policy_fired=True",
        per_trial=(TrialResult(outcome=Outcome.FAIL, reason="x"),),
    )
    meta = RunMetadata(run_id="cli-sum", assertstate_version="0", contract_hash="h")
    run_dir = write_run(tmp_path, "cli-sum", v, meta)
    assert main(["report", str(run_dir), "--format", "summary"]) == 0
    out = capsys.readouterr().out
    assert "Verdict: **FAIL**" in out
    data = json.loads((run_dir / "run.json").read_text())
    assert data["verdict"]["failed"] == 3  # summary came from the real redacted bundle
