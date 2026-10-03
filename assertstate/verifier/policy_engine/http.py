"""forbid.http — network-trace policy, e.g. 200-with-error-body (FEATURE-SPEC §4.4).

Consumes trusted BrowserObservations. Fires when a captured request matches `match` AND any
`body_matches` jsonpath is present in the response body (a bare match with no body predicate
fires on the match alone). Gating only when trusted capture is present.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from assertstate.domain.contract import HttpPolicy
from assertstate.domain.trace import BrowserObservations
from assertstate.verifier.jsonpath import JsonPathError, extract
from assertstate.verifier.policy_engine.base import PolicyResult


def _path_matches(glob: str, path: str) -> bool:
    return path.startswith(glob[:-1]) if glob.endswith("*") else path == glob


def evaluate_http(policy: HttpPolicy, observations: BrowserObservations) -> PolicyResult:
    gating = observations.status == "captured"
    hits = 0
    for rec in observations.network:
        m = policy.match
        if m.method and str(rec.get("method", "")).upper() != m.method.upper():
            continue
        if not _path_matches(m.path_glob, urlparse(str(rec.get("url", ""))).path):
            continue
        if m.status and rec.get("status") not in m.status:
            continue
        if not policy.body_matches:
            hits += 1
            continue
        body = rec.get("resp_body") or ""
        try:
            data = json.loads(body) if body else None
        except json.JSONDecodeError:
            data = None
        for jp in policy.body_matches:
            try:
                found, _ = extract(jp, data) if data is not None else (False, None)
            except JsonPathError:
                found = False
            if found:
                hits += 1
    fired = hits > 0
    detail = f"http hits={hits} fired={fired} gating={gating} capture={observations.status}"
    return PolicyResult(kind="http", fired=fired, gating=gating, detail=detail)
