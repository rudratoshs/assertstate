"""forbid.external_* — the agent left the app's domains / sent data out (FEATURE-SPEC §5.3).

Consumes trusted BrowserObservations. `deny_domains` fires on those hosts; otherwise any host
not in (app hosts ∪ allow_domains) is external. `external_data_transfer` additionally requires
`body_match` to appear in the OUTBOUND request (the URL/query-string or the request body — the
exfil direction), best-effort (defeated by encoding; the reliable parts are navigation and
domain allow/deny). Gating only when trusted capture is present.
"""

from __future__ import annotations

from collections.abc import Iterable

from assertstate.domain.contract import EXT_DATA_TRANSFER, ExternalPolicy
from assertstate.domain.trace import BrowserObservations
from assertstate.verifier.policy_engine.base import PolicyResult


def evaluate_external(
    policy: ExternalPolicy, observations: BrowserObservations, app_hosts: Iterable[str]
) -> PolicyResult:
    gating = observations.status == "captured"
    allowed = set(app_hosts) | set(policy.allow_domains)
    hits: list[str] = []
    for rec in observations.network:
        host = str(rec.get("host", ""))
        if not host:
            continue
        if policy.deny_domains:
            external = host in policy.deny_domains
        else:
            external = host not in allowed
        if not external:
            continue
        if policy.kind == EXT_DATA_TRANSFER and policy.body_match:
            # Match what was SENT OUT: the URL/query-string and the REQUEST body — not the
            # response (which is inbound and cannot evidence exfil).
            payload = str(rec.get("url", "")) + " " + str(rec.get("req_body", ""))
            if policy.body_match not in payload:
                continue
        hits.append(host)
    fired = len(hits) > 0
    return PolicyResult(
        kind="external",
        fired=fired,
        gating=gating,
        detail=f"external[{policy.kind}] hits={len(hits)} hosts={hits[:3]} "
        f"fired={fired} gating={gating} capture={observations.status}",
    )
