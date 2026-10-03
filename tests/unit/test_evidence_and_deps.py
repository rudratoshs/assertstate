"""Named P1 tests: evidence fail-closed + hashing (§34, §36.9) and dependency/INV-8 (§34)."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

from assertstate.domain.metadata import RunMetadata
from assertstate.domain.result import Outcome, TrialResult
from assertstate.domain.verdict import RunOutcome, RunVerdict
from assertstate.evidence.bundle import EvidenceError, write_run


def _verdict() -> RunVerdict:
    return RunVerdict(
        verdict=RunOutcome.PASS,
        total_trials=1,
        valid_trials=1,
        passed=1,
        failed=0,
        errored=0,
        skipped=0,
        pass_rate=1.0,
        wilson_lower=0.3,
        confidence=0.95,
        side="one_sided",
        pass_threshold=0.25,
        error_rate=0.0,
        skip_rate=0.0,
        reason="ok",
        per_trial=(TrialResult(outcome=Outcome.PASS),),
    )


def _meta() -> RunMetadata:
    return RunMetadata(run_id="t", assertstate_version="0", contract_hash="h")


def test_redaction_failure_emits_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # If redaction raises, write_run must emit NOTHING (fail-closed, §36.9).
    def boom(_: object) -> object:
        raise RuntimeError("redaction blew up")

    monkeypatch.setattr("assertstate.evidence.bundle.json_safe", boom)
    with pytest.raises(EvidenceError):
        write_run(tmp_path, "t", _verdict(), _meta())
    assert not (tmp_path / "runs" / "t" / "run.json").exists()  # nothing written


def test_manifest_hashes_match_and_are_stable(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, "t", _verdict(), _meta())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest, "manifest must list files"
    for rel, digest in manifest.items():
        actual = hashlib.sha256((run_dir / rel).read_bytes()).hexdigest()
        assert actual == digest, f"hash mismatch for {rel}"


def test_verifier_imports_no_model_client() -> None:
    for mod in (
        "assertstate.verifier.expect.evaluator",
        "assertstate.verifier.policy_engine.db_delta",
        "assertstate.verifier.policy_engine.http",
        "assertstate.verifier.policy_engine.external",
        "assertstate.stats.aggregate",
    ):
        importlib.import_module(mod)
    forbidden = {"openai", "anthropic", "browser_use"}
    assert not (forbidden & set(sys.modules)), "verifier/stats must not pull a model client"


def test_inv8_verdict_has_no_agent_claim_input() -> None:
    # The verdict function must not take any agent-reported field (INV-8).
    from assertstate.orchestrator.runner import _verify

    params = set(inspect.signature(_verify).parameters)
    assert not (params & {"trace", "agent_claimed_done", "claimed_done", "agent"})
