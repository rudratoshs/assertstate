"""JUnit XML reporter (FEATURE-SPEC §11). Pure formatter over a stored run."""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape, quoteattr


def to_junit(verdict: dict[str, Any], run_id: str) -> str:
    trials = verdict.get("per_trial") or []
    suite = (
        f'<testsuite name={quoteattr(run_id)} tests="{verdict.get("total_trials", 0)}" '
        f'failures="{verdict.get("failed", 0)}" errors="{verdict.get("errored", 0)}" '
        f'skipped="{verdict.get("skipped", 0)}">'
    )
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', suite]
    for i, t in enumerate(trials):
        outcome = t.get("outcome")
        reason = escape(str(t.get("reason", "")))
        lines.append(f'  <testcase name="trial-{i}" classname={quoteattr(run_id)}>')
        if outcome == "FAIL":
            lines.append(f'    <failure message="{reason}">{reason}</failure>')
        elif outcome == "ERROR":
            lines.append(f'    <error message="{reason}">{reason}</error>')
        elif outcome == "SKIPPED":
            lines.append(f'    <skipped message="{reason}"/>')
        lines.append("  </testcase>")
    lines.append("</testsuite>")
    return "\n".join(lines) + "\n"
