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
