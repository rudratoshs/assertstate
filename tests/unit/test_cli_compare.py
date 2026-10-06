"""`assertstate compare` regression gate (FEATURE-SPEC §8.5/§10): exit 1 iff candidate is
significantly worse than baseline."""

from __future__ import annotations

import json
from pathlib import Path

from assertstate.cli import main


def _run_json(path: Path, passed: int, valid: int) -> Path:
    path.write_text(
        json.dumps({"run_id": path.stem, "verdict": {"passed": passed, "valid_trials": valid}}),
        encoding="utf-8",
    )
    return path


def test_compare_flags_regression(tmp_path: Path) -> None:
    base = _run_json(tmp_path / "base.json", 30, 30)  # 100%
    cand = _run_json(tmp_path / "cand.json", 24, 30)  # 80% -> significantly worse
    assert main(["compare", str(base), str(cand)]) == 1


def test_compare_passes_when_not_worse(tmp_path: Path) -> None:
    base = _run_json(tmp_path / "base.json", 30, 30)
    cand = _run_json(tmp_path / "cand.json", 30, 30)  # equal -> no regression
    assert main(["compare", str(base), str(cand)]) == 0


def test_compare_missing_run_is_usage_error(tmp_path: Path) -> None:
    base = _run_json(tmp_path / "base.json", 30, 30)
    assert main(["compare", str(base), str(tmp_path / "nope.json")]) == 2


def _run_json_paired(path: Path, outcomes: list[str]) -> Path:
    path.write_text(
        json.dumps(
            {
                "run_id": path.stem,
                "verdict": {
                    "passed": sum(o == "PASS" for o in outcomes),
                    "valid_trials": sum(o in ("PASS", "FAIL") for o in outcomes),
                    "per_trial": [{"outcome": o} for o in outcomes],
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_compare_paired_flags_regression(tmp_path: Path) -> None:
    # Same 20 scenarios: baseline passes all; candidate fails 12 (b=12, c=0) -> McNemar FAIL.
    base = _run_json_paired(tmp_path / "base.json", ["PASS"] * 20)
    cand = _run_json_paired(tmp_path / "cand.json", ["FAIL"] * 12 + ["PASS"] * 8)
    assert main(["compare", "--paired", str(base), str(cand)]) == 1


def test_compare_paired_no_regression_when_symmetric(tmp_path: Path) -> None:
    # Discordances balanced (b=2, c=2) -> not significantly worse.
    base = _run_json_paired(
        tmp_path / "base.json", ["PASS", "PASS", "FAIL", "FAIL"] + ["PASS"] * 16
    )
    cand = _run_json_paired(
        tmp_path / "cand.json", ["FAIL", "FAIL", "PASS", "PASS"] + ["PASS"] * 16
    )
    assert main(["compare", "--paired", str(base), str(cand)]) == 0


def test_compare_paired_without_per_trial_is_usage_error(tmp_path: Path) -> None:
    # The non-paired fixtures have no per_trial -> paired compare fails closed (usage error).
    base = _run_json(tmp_path / "base.json", 30, 30)
    cand = _run_json(tmp_path / "cand.json", 24, 30)
    assert main(["compare", "--paired", str(base), str(cand)]) == 2
