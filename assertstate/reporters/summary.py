"""GitHub Step-Summary reporter (FEATURE-SPEC §5, §10).

Renders a concise Markdown summary of a Run from the ALREADY-REDACTED run.json (verdict scalars
+ the scope statement only). It never reads per-trial `detail`/`query` or any raw oracle value, so
it cannot leak secrets — it reuses the evidence redaction by consuming the redacted bundle, not by
re-deriving anything. Pure formatter; it never changes a verdict.
"""

from __future__ import annotations

from typing import Any


def _fmt(x: Any) -> str:
    return "n/a" if x is None else str(x)


def to_step_summary(
    data: dict[str, Any], *, contract: str = "", app: str = "", scenario: str = ""
) -> str:
    """`data` is the parsed run.json. `contract`/`app`/`scenario` are optional run-context labels
    (the stored bundle keeps only a contract HASH, so the caller passes human labels when it has
    them). Output is safe to paste into $GITHUB_STEP_SUMMARY."""
    v = data.get("verdict", {})
    meta = data.get("metadata", {})
    scope = data.get("scope", {})
    verdict = str(v.get("verdict", "UNKNOWN"))
    total = v.get("total_trials")
    valid = v.get("valid_trials")

    lines = ["## AssertState", ""]
    lines.append(f"- **Contract:** `{contract or meta.get('contract_hash', 'n/a')}`")
    lines.append(f"- **Application:** `{app or meta.get('adapter_name', 'n/a')}`")
    lines.append(f"- **Scenario:** `{scenario or meta.get('scenario_id') or 'n/a'}`")
    lines.append(f"- **Trials:** {_fmt(total)} (valid {_fmt(valid)})")
    lines.append("")
    lines.append(f"### Verdict: **{verdict}**")
    lines.append("")
    lines.append(
        f"| PASS | FAIL | ERROR | SKIPPED |\n|--:|--:|--:|--:|\n"
        f"| {_fmt(v.get('passed'))} | {_fmt(v.get('failed'))} | "
        f"{_fmt(v.get('errored'))} | {_fmt(v.get('skipped'))} |"
    )
    lines.append("")
    lines.append(
        f"- **Wilson lower bound:** {_fmt(v.get('wilson_lower'))} "
        f"({_fmt(v.get('side'))}, confidence {_fmt(v.get('confidence'))}) "
        f"vs pass_threshold {_fmt(v.get('pass_threshold'))}"
    )
    # No single "completeness" scalar exists; report the three completeness signals honestly.
    lines.append(
        f"- **Completeness:** valid_trials={_fmt(valid)} · error_rate={_fmt(v.get('error_rate'))} "
        f"· skip_rate={_fmt(v.get('skip_rate'))}"
    )
    if v.get("reason"):
        lines.append(f"- **Reason:** {v.get('reason')}")
    if verdict == "FAIL":
        lines.append("")
        lines.append(
            "> ❌ **The authoritative application-state contract FAILED** — the agent's own "
            "report is not the source of truth; the read-only oracle + settled side-effect deltas "
            "decided this. See the uploaded evidence bundle."
        )
    if scope.get("establishes"):
        lines.append("")
        lines.append(f"<sub>Scope — establishes: {scope['establishes']}</sub>")
        lines.append(
            f"<sub>Scope — does NOT establish: {scope.get('does_not_establish', '')}</sub>"
        )
    lines.append("")
    lines.append(
        f"- **Evidence:** `{data.get('run_id', 'n/a')}` bundle (uploaded as a CI artifact)"
    )
    return "\n".join(lines) + "\n"
