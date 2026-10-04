"""Local artifact store + redacted evidence bundle (DEVELOPMENT §27, §30).

Writes .assertstate/runs/<run-id>/ containing run.json, trials/*.json, junit.xml, report.html,
manifest.json, the copied contract.yaml, and evidence.zip. Durable + atomic (§30): the bundle is
assembled in a sibling staging dir carrying an `.incomplete` marker, fsync'd, then atomically
renamed into place — so a reader never sees a half-written run and an interrupted write leaves only
a clearly-marked staging dir. An existing run-id is never overwritten. Redaction is fail-closed:
if it raises, NOTHING is written (no unredacted fallback).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assertstate.domain.metadata import RunMetadata
from assertstate.domain.verdict import RunVerdict
from assertstate.evidence.redact import redact

_INCOMPLETE_MARKER = ".incomplete"


class EvidenceError(Exception):
    """Evidence could not be assembled/redacted; nothing is emitted (fail-closed)."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scope_statement(safe_verdict: dict[str, Any], safe_meta: dict[str, Any]) -> dict[str, str]:
    """A self-describing scope statement (FEATURE-SPEC §11): what this run establishes and what it
    does NOT. Composed only from already-safe verdict/metadata scalars — never any row data."""
    v = safe_verdict
    return {
        "establishes": (
            f"Verdict {v.get('verdict')} over {v.get('total_trials')} trials "
            f"({v.get('valid_trials')} valid: {v.get('passed')} PASS / {v.get('failed')} FAIL) — "
            f"the application's own state (read-only oracle) satisfied the contract's expectations "
            f"and no gating side-effect policy fired, at Wilson lower bound "
            f"{v.get('wilson_lower')} ({v.get('side')}, confidence {v.get('confidence')}) vs "
            f"pass_threshold {v.get('pass_threshold')}. Canonicalizer "
            f"{safe_meta.get('canonicalizer_version')}."
        ),
        "does_not_establish": (
            "Correctness of DB columns the contract does not project; behavior outside the "
            "contract's assertions; causal attribution of side-effects under 'observed' "
            "(shared-staging) attribution, where db_delta is non-gating; properties needing "
            "instrumentation not present in this run (e.g. HTTPS/CDP capture); and anything about "
            "the agent's internal reasoning (agent_claimed_done is recorded, never trusted)."
        ),
    }


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    # Directory fsync makes the rename/creation durable; not supported on every platform/FS.
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_run(
    base_dir: Path,
    run_id: str,
    verdict: RunVerdict,
    metadata: RunMetadata,
    *,
    allow_fields: tuple[str, ...] = (),
    contract_path: Path | None = None,
) -> Path:
    runs_dir = base_dir / "runs"
    run_dir = runs_dir / run_id
    if run_dir.exists():
        # No-overwrite (§30): a run-id's evidence is immutable once written.
        raise EvidenceError(f"refusing to overwrite existing run evidence: {run_dir}")

    try:
        safe_verdict = redact(verdict, allow_fields=allow_fields)
        safe_meta = redact(metadata, allow_fields=allow_fields)
        safe_trials = [redact(t, allow_fields=allow_fields) for t in verdict.per_trial]
    except Exception as exc:  # fail-closed: do not emit a partially/unredacted bundle
        raise EvidenceError(f"redaction failed, nothing written: {exc}") from exc

    # Assemble in a sibling staging dir, marked incomplete until the atomic rename succeeds.
    runs_dir.mkdir(parents=True, exist_ok=True)
    staging = runs_dir / f".staging-{run_id}-{uuid.uuid4().hex[:8]}"
    trials_dir = staging / "trials"
    trials_dir.mkdir(parents=True, exist_ok=False)
    (staging / _INCOMPLETE_MARKER).write_text("writing\n", encoding="utf-8")

    try:
        run_json = staging / "run.json"
        run_json.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "written_at": datetime.now(timezone.utc).isoformat(),
                    "verdict": safe_verdict,
                    "metadata": safe_meta,
                    "scope": _scope_statement(dict(safe_verdict), dict(safe_meta)),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        files = [run_json]
        for i, trial in enumerate(safe_trials):
            p = trials_dir / f"trial-{i:04d}.json"
            p.write_text(json.dumps(trial, indent=2), encoding="utf-8")
            files.append(p)

        # JUnit + HTML reporters (pure formatters over the redacted verdict; never alter it).
        from assertstate.reporters.html import to_html
        from assertstate.reporters.junit import to_junit

        junit = staging / "junit.xml"
        junit.write_text(to_junit(dict(safe_verdict), run_id), encoding="utf-8")
        report_html = staging / "report.html"
        report_html.write_text(to_html(dict(safe_verdict), run_id), encoding="utf-8")
        files += [junit, report_html]

        # Copy the source contract verbatim for provenance (§30), when provided.
        if contract_path is not None:
            contract_copy = staging / "contract.yaml"
            contract_copy.write_bytes(Path(contract_path).read_bytes())
            files.append(contract_copy)

        manifest: dict[str, Any] = {str(p.relative_to(staging)): _sha256(p) for p in files}
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        files.append(manifest_path)

        # evidence.zip: a single-file archive of the whole bundle (derived; not in the manifest).
        zip_path = staging / "evidence.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in files:
                zf.write(p, p.relative_to(staging).as_posix())

        # Durability: fsync every file, drop the incomplete marker, then atomically publish.
        for p in [*files, zip_path]:
            _fsync_file(p)
        (staging / _INCOMPLETE_MARKER).unlink()
        _fsync_dir(staging)
        os.replace(staging, run_dir)  # atomic within the same filesystem
        _fsync_dir(runs_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)  # leave no half-written bundle behind
        raise

    return run_dir
