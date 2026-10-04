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
    def boom(_: object, **__: object) -> object:
        raise RuntimeError("redaction blew up")

    monkeypatch.setattr("assertstate.evidence.bundle.redact", boom)
    with pytest.raises(EvidenceError):
        write_run(tmp_path, "t", _verdict(), _meta())
    assert not (tmp_path / "runs" / "t" / "run.json").exists()  # nothing written


def test_redaction_is_allowlist_not_denylist(tmp_path: Path) -> None:
    """A benign-NAMED key carrying a secret value: a denylist would leak it; the allowlist masks it.

    `refs` is allowlisted (emitted as a dict) but its sub-key `notes` is NOT, so its value —
    which contains a DSN whose name no denylist token would catch — must be masked.
    """
    secret = "postgres://admin:hunter2@db.internal/app"  # no 'secret'/'token'/'dsn' in the KEY
    trial = TrialResult(outcome=Outcome.PASS, refs={"notes": secret, "agent_claimed_done": "True"})
    v = _verdict()
    v = RunVerdict(**{**v.__dict__, "per_trial": (trial,)})
    run_dir = write_run(tmp_path, "t", v, _meta())
    blob = (run_dir / "trials" / "trial-0000.json").read_text()
    assert secret not in blob, "non-allowlisted key leaked its value (denylist behaviour)"
    assert "***REDACTED***" in blob, "non-allowlisted value must be masked"
    assert '"agent_claimed_done": "True"' in blob, "allowlisted key must pass through"


def test_expect_detail_and_query_masked_by_default(tmp_path: Path) -> None:
    """The exact leak two audits proved: expect_results `detail` embeds a raw observed DB value
    and `query` embeds SQL WHERE-clause PII. Both must be masked by default (§11 / §28)."""
    secret = "sk-live-DEADBEEF-SECRET-TOKEN"
    pii_query = "SELECT api_key FROM creds WHERE email='alice@acme.com'"
    trial = TrialResult(
        outcome=Outcome.PASS,
        expect_results=(
            {
                "comparator": "equals",
                "ok": True,
                "present": True,
                "query": pii_query,
                "detail": f"'{secret}' equals 'x' -> False",
            },
        ),
    )
    v = RunVerdict(**{**_verdict().__dict__, "per_trial": (trial,)})
    run_dir = write_run(tmp_path, "t", v, _meta())
    blob = (run_dir / "trials" / "trial-0000.json").read_text()
    assert secret not in blob, "raw observed DB value leaked via `detail`"
    assert "alice@acme.com" not in blob, "WHERE-clause PII leaked via `query`"
    assert "api_key FROM creds" not in blob, "raw SQL query leaked"
    # ...but the safe structural fields survive so the check is still identifiable.
    assert '"comparator": "equals"' in blob
    assert '"present": true' in blob


def test_expect_detail_query_emitted_only_with_allow_fields(tmp_path: Path) -> None:
    trial = TrialResult(
        outcome=Outcome.PASS,
        expect_results=(
            {
                "comparator": "equals",
                "ok": True,
                "present": True,
                "query": "SELECT status FROM payments",
                "detail": "'paid' equals 'paid'",
            },
        ),
    )
    v = RunVerdict(**{**_verdict().__dict__, "per_trial": (trial,)})
    run_dir = write_run(tmp_path, "t", v, _meta(), allow_fields=("query", "detail"))
    blob = (run_dir / "trials" / "trial-0000.json").read_text()
    assert "SELECT status FROM payments" in blob, "allow_fields must opt query back in"
    assert "'paid' equals 'paid'" in blob, "allow_fields must opt detail back in"


def test_redaction_allow_fields_widens(tmp_path: Path) -> None:
    # The operator's config `allow_fields` lets a named key through.
    trial = TrialResult(outcome=Outcome.PASS, refs={"notes": "safe-build-id-42"})
    v = RunVerdict(**{**_verdict().__dict__, "per_trial": (trial,)})
    run_dir = write_run(tmp_path, "t", v, _meta(), allow_fields=("notes",))
    blob = (run_dir / "trials" / "trial-0000.json").read_text()
    assert "safe-build-id-42" in blob, "allow_fields must widen the allowlist"


def test_redaction_masks_scalar_strings_inside_lists() -> None:
    # A bare string inside a list has no key to gate it -> default-deny (mask). Dicts in the list
    # still recurse and are key-gated. Closes the list-scalar bypass an audit flagged.
    from assertstate.evidence.redact import MASK, redact

    out = redact({"per_trial": ["postgres://u:SECRET@h/db", {"ok": True, "query": "SELECT 1"}]})
    assert out["per_trial"][0] == MASK, "scalar string in a list must be masked"
    assert out["per_trial"][1]["ok"] is True, "dict element still recurses"
    assert out["per_trial"][1]["query"] == MASK, "non-allowlisted key inside list dict still masked"


def test_default_allow_covers_every_evidence_field() -> None:
    # Drift guard: every evidence dataclass field must be on the allowlist, else it is silently
    # masked. Adding a field forces a conscious allow/deny decision here (FEATURE-SPEC §11).
    from dataclasses import fields

    from assertstate.domain.result import SettlementRecord
    from assertstate.evidence.redact import _DEFAULT_ALLOW

    names: set[str] = set()
    for dc in (RunVerdict, TrialResult, SettlementRecord, RunMetadata):
        names |= {f.name for f in fields(dc)}
    missing = names - _DEFAULT_ALLOW
    assert not missing, f"evidence fields not on the redaction allowlist: {sorted(missing)}"


def test_manifest_hashes_match_and_are_stable(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, "t", _verdict(), _meta())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest, "manifest must list files"
    for rel, digest in manifest.items():
        actual = hashlib.sha256((run_dir / rel).read_bytes()).hexdigest()
        assert actual == digest, f"hash mismatch for {rel}"


def test_bundle_is_durable_and_atomic(tmp_path: Path) -> None:
    # §30: atomic publish (no leftover staging/marker), evidence.zip, copied contract.yaml.
    import zipfile

    contract = tmp_path / "c.yaml"
    contract.write_text("task: t\n", encoding="utf-8")
    run_dir = write_run(tmp_path, "r1", _verdict(), _meta(), contract_path=contract)

    assert (run_dir / "evidence.zip").exists()
    assert (run_dir / "contract.yaml").read_text() == "task: t\n"
    assert not (run_dir / ".incomplete").exists(), "incomplete marker must be gone after publish"
    assert not list(tmp_path.glob("runs/.staging-*")), "no staging dir may remain"
    with zipfile.ZipFile(run_dir / "evidence.zip") as zf:
        names = set(zf.namelist())
    assert {"run.json", "manifest.json", "contract.yaml"} <= names


def test_bundle_refuses_to_overwrite_existing_run(tmp_path: Path) -> None:
    write_run(tmp_path, "r1", _verdict(), _meta())
    with pytest.raises(EvidenceError, match="overwrite"):
        write_run(tmp_path, "r1", _verdict(), _meta())  # same run-id -> immutable (§30)


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
