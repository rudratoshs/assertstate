"""Regression history (FEATURE-SPEC §13, P3): scan the local evidence store, show the pass-rate
trend, and flag the latest run as a regression vs the prior run of the same contract."""

from __future__ import annotations

import json
from pathlib import Path

from assertstate.cli import main
from assertstate.history import latest_regression, load_history


def _write_run(
    store: Path, run_id: str, *, written_at: str, contract_hash: str, passed: int, valid: int
) -> None:
    d = store / "runs" / run_id
    d.mkdir(parents=True)
    outcome = "PASS" if valid and passed == valid else "FAIL"
    (d / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "written_at": written_at,
                "verdict": {
                    "verdict": outcome,
                    "passed": passed,
                    "valid_trials": valid,
                    "pass_rate": (passed / valid) if valid else None,
                    "wilson_lower": None,
                },
                "metadata": {"contract_hash": contract_hash, "adapter_name": "noop"},
            }
        ),
        encoding="utf-8",
    )


def test_load_history_orders_by_written_at(tmp_path: Path) -> None:
    _write_run(
        tmp_path, "r2", written_at="2026-10-02T00:00:00Z", contract_hash="h", passed=30, valid=30
    )
    _write_run(
        tmp_path, "r1", written_at="2026-10-01T00:00:00Z", contract_hash="h", passed=30, valid=30
    )
    recs = load_history(tmp_path)
    assert [r.run_id for r in recs] == ["r1", "r2"]  # oldest first


def test_latest_regression_flags_a_drop(tmp_path: Path) -> None:
    _write_run(
        tmp_path, "base", written_at="2026-10-01T00:00:00Z", contract_hash="h", passed=30, valid=30
    )
    _write_run(
        tmp_path, "cand", written_at="2026-10-02T00:00:00Z", contract_hash="h", passed=20, valid=30
    )
    reg = latest_regression(load_history(tmp_path))
    assert reg is not None and reg.regressed is True


def test_latest_regression_none_when_only_one_run(tmp_path: Path) -> None:
    _write_run(
        tmp_path, "only", written_at="2026-10-01T00:00:00Z", contract_hash="h", passed=30, valid=30
    )
    assert latest_regression(load_history(tmp_path)) is None


def test_latest_regression_ignores_other_contracts(tmp_path: Path) -> None:
    # The prior run is a DIFFERENT contract -> not a comparable pair -> no regression verdict.
    _write_run(
        tmp_path, "other", written_at="2026-10-01T00:00:00Z", contract_hash="x", passed=0, valid=30
    )
    _write_run(
        tmp_path, "cand", written_at="2026-10-02T00:00:00Z", contract_hash="h", passed=30, valid=30
    )
    assert latest_regression(load_history(tmp_path)) is None


def test_history_cli_gate_exits_1_on_regression(tmp_path: Path) -> None:
    _write_run(
        tmp_path, "base", written_at="2026-10-01T00:00:00Z", contract_hash="h", passed=30, valid=30
    )
    _write_run(
        tmp_path, "cand", written_at="2026-10-02T00:00:00Z", contract_hash="h", passed=18, valid=30
    )
    assert main(["history", "--store", str(tmp_path), "--gate"]) == 1


def test_history_cli_no_gate_flag_exits_0(tmp_path: Path) -> None:
    _write_run(
        tmp_path, "base", written_at="2026-10-01T00:00:00Z", contract_hash="h", passed=30, valid=30
    )
    _write_run(
        tmp_path, "cand", written_at="2026-10-02T00:00:00Z", contract_hash="h", passed=18, valid=30
    )
    assert main(["history", "--store", str(tmp_path)]) == 0  # informational without --gate


def test_history_cli_empty_store_exits_0(tmp_path: Path) -> None:
    assert main(["history", "--store", str(tmp_path)]) == 0


def test_history_cli_corrupt_run_is_skipped(tmp_path: Path) -> None:
    _write_run(
        tmp_path, "ok", written_at="2026-10-01T00:00:00Z", contract_hash="h", passed=30, valid=30
    )
    bad = tmp_path / "runs" / "bad"
    bad.mkdir(parents=True)
    (bad / "run.json").write_text("{ not json", encoding="utf-8")
    assert len(load_history(tmp_path)) == 1  # corrupt dir skipped, never crashes
