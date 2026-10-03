"""Local artifact store + redacted evidence bundle (DEVELOPMENT §27, §30).

Writes .assertstate/runs/<run-id>/{run.json, trials/*.json, manifest.json}. Redaction is
fail-closed: if it raises, nothing is written (no unredacted fallback).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assertstate.domain.metadata import RunMetadata
from assertstate.domain.verdict import RunVerdict
from assertstate.evidence.redact import json_safe


class EvidenceError(Exception):
    """Evidence could not be assembled/redacted; nothing is emitted (fail-closed)."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_run(base_dir: Path, run_id: str, verdict: RunVerdict, metadata: RunMetadata) -> Path:
    run_dir = base_dir / "runs" / run_id
    trials_dir = run_dir / "trials"
    try:
        safe_verdict = json_safe(verdict)
        safe_meta = json_safe(metadata)
        safe_trials = [json_safe(t) for t in verdict.per_trial]
    except Exception as exc:  # fail-closed: do not emit a partially/unredacted bundle
        raise EvidenceError(f"redaction failed, nothing written: {exc}") from exc

    trials_dir.mkdir(parents=True, exist_ok=True)
    run_json = run_dir / "run.json"
    run_json.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "written_at": datetime.now(timezone.utc).isoformat(),
                "verdict": safe_verdict,
                "metadata": safe_meta,
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

    junit = run_dir / "junit.xml"
    junit.write_text(to_junit(dict(safe_verdict), run_id), encoding="utf-8")
    report_html = run_dir / "report.html"
    report_html.write_text(to_html(dict(safe_verdict), run_id), encoding="utf-8")
    files += [junit, report_html]

    manifest: dict[str, Any] = {str(p.relative_to(run_dir)): _sha256(p) for p in files}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return run_dir
