"""Regression history (FEATURE-SPEC §13, P3 — local, demand-driven).

A read-only scan of the local evidence store (`.assertstate/runs/*/run.json`): groups past runs by
contract (and scenario), orders them by write time, and surfaces the pass-rate trend plus whether
the LATEST run of a contract is a statistically significant regression vs the immediately prior run
of the same contract (reusing the §8.5 two-proportion test — never Wilson-interval overlap).

Self-contained: no network, no new dependency, no control-plane. It reads the same redacted run.json
the evidence bundle already writes, so it never sees secrets or raw oracle values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from assertstate.stats.compare import ComparisonResult, two_proportion


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    written_at: str  # ISO-8601 UTC (sort key)
    contract_hash: str
    scenario_id: str | None
    adapter_name: str | None
    outcome: str  # RunOutcome value (PASS/FAIL/INCONCLUSIVE)
    passed: int
    valid_trials: int
    pass_rate: float | None
    wilson_lower: float | None


def _load_one(run_json: Path) -> RunRecord | None:
    try:
        doc = json.loads(run_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None  # a partial/corrupt run dir is skipped, never crashes the history view
    v = doc.get("verdict") or {}
    m = doc.get("metadata") or {}
    ch = m.get("contract_hash")
    if not ch:
        return None  # pre-metadata or malformed run — not groupable
    return RunRecord(
        run_id=str(doc.get("run_id") or run_json.parent.name),
        written_at=str(doc.get("written_at") or m.get("timestamp_tz") or ""),
        contract_hash=str(ch),
        scenario_id=m.get("scenario_id"),
        adapter_name=m.get("adapter_name"),
        outcome=str(v.get("verdict") or "UNKNOWN"),
        passed=int(v.get("passed") or 0),
        valid_trials=int(v.get("valid_trials") or 0),
        pass_rate=v.get("pass_rate"),
        wilson_lower=v.get("wilson_lower"),
    )


def load_history(
    store_dir: Path,
    *,
    contract_hash: str | None = None,
    scenario: str | None = None,
) -> list[RunRecord]:
    """All runs in the store (optionally filtered), oldest first by write time."""
    runs_dir = store_dir / "runs"
    records: list[RunRecord] = []
    if runs_dir.is_dir():
        for child in runs_dir.iterdir():
            if child.name.startswith(".staging-") or not child.is_dir():
                continue
            rec = _load_one(child / "run.json")
            if rec is None:
                continue
            if contract_hash and rec.contract_hash != contract_hash:
                continue
            if scenario is not None and rec.scenario_id != scenario:
                continue
            records.append(rec)
    records.sort(key=lambda r: (r.written_at, r.run_id))
    return records


def latest_regression(
    records: list[RunRecord], *, confidence: float = 0.95
) -> ComparisonResult | None:
    """Compare the latest run to the immediately prior run of the SAME contract (two-proportion,
    one-sided "worse"). None when there are fewer than two comparable runs."""
    if len(records) < 2:
        return None
    cand = records[-1]
    prior = next(
        (r for r in reversed(records[:-1]) if r.contract_hash == cand.contract_hash),
        None,
    )
    if prior is None or prior.valid_trials == 0 or cand.valid_trials == 0:
        return None
    return two_proportion(
        prior.passed,
        prior.valid_trials,
        cand.passed,
        cand.valid_trials,
        confidence=confidence,
        side="one_sided",
    )
