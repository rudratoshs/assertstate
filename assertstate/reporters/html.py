"""HTML reporter (FEATURE-SPEC §11). Pure formatter over a stored run."""

from __future__ import annotations

import html as _html
from typing import Any

_COLORS = {"PASS": "#1a7f37", "FAIL": "#cf222e", "ERROR": "#9a6700", "INCONCLUSIVE": "#6e7781"}


def to_html(verdict: dict[str, Any], run_id: str) -> str:
    v = str(verdict.get("verdict", "?"))
    color = _COLORS.get(v, "#6e7781")
    rows = "".join(
        f"<tr><td>trial-{i}</td>"
        f"<td style='color:{_COLORS.get(str(t.get('outcome')), '#333')}'>{t.get('outcome')}</td>"
        f"<td>{_html.escape(str(t.get('reason', '')))}</td></tr>"
        for i, t in enumerate(verdict.get("per_trial") or [])
    )
    wl = verdict.get("wilson_lower")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>AssertState — {_html.escape(run_id)}</title></head>
<body style="font-family:sans-serif;max-width:56em;margin:2em auto">
<h1>{_html.escape(run_id)}:
  <span style="color:{color}">{_html.escape(v)}</span></h1>
<p>{verdict.get("passed", 0)} PASS · {verdict.get("failed", 0)} FAIL ·
   {verdict.get("errored", 0)} ERROR · {verdict.get("skipped", 0)} SKIPPED —
   wilson_lower={wl}, threshold={verdict.get("pass_threshold")}</p>
<p>{_html.escape(str(verdict.get("reason", "")))}</p>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>trial</th><th>outcome</th><th>reason</th></tr>
{rows}
</table>
</body></html>
"""
