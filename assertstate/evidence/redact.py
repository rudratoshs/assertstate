"""Fail-closed ALLOWLIST redaction + JSON-safe serialization for evidence.

Spec: FEATURE-SPEC §11, DEVELOPMENT §28 — redaction is an ALLOWLIST (default-deny):
a value is emitted into evidence ONLY if its key is on the allowlist; every other
value is masked. This keeps row data, response bodies, headers, DSNs and credentials
out of artifacts even when a future field would otherwise carry them.

`_DEFAULT_ALLOW` is the fixed evidence schema (verdict/trial/metadata structural fields
+ the orchestrator's own result-dict keys). The operator widens it per app via
`redaction.allow_fields` in the config. A drift-guard unit test asserts every evidence
dataclass field name is on the allowlist, so adding a field forces a conscious decision.

Fail-closed: if redaction raises, callers emit NOTHING rather than an unredacted artifact.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

MASK = "***REDACTED***"
_MAX_STR = 4096

# Belt-and-braces: even an allowlisted key is masked if its NAME looks like a secret.
_SENSITIVE = ("cred", "dsn", "password", "secret", "token", "authorization", "cookie", "api_key")

# The evidence schema that MAY be emitted verbatim. Everything else is masked (default-deny).
# Keep in sync with the evidence dataclasses — tests/unit/test_evidence_and_deps.py enforces it.
_DEFAULT_ALLOW: frozenset[str] = frozenset(
    {
        # RunVerdict
        "verdict",
        "total_trials",
        "valid_trials",
        "passed",
        "failed",
        "errored",
        "skipped",
        "pass_rate",
        "wilson_lower",
        "confidence",
        "side",
        "pass_threshold",
        "error_rate",
        "skip_rate",
        "reason",
        "per_trial",
        # TrialResult
        "outcome",
        "attribution",
        "expect_results",
        "policy_results",
        "budget_results",
        "settlement",
        "refs",
        # SettlementRecord
        "mode",
        "causal_start_at",
        "started_at",
        "completed_at",
        "bound_or_drain_signal",
        # RunMetadata
        "run_id",
        "assertstate_version",
        "contract_hash",
        "scenario_id",
        "adapter_name",
        "adapter_version",
        "model_provider",
        "system_prompt_hash",
        "browser_version",
        "app_build_git_sha",
        "db_schema_fingerprint",
        "fixture_version",
        "env_image",
        "canonicalizer_version",
        "statistics_config",
        "settlement_config",
        "timestamp_tz",
        # orchestrator result-dict keys (expect_results / policy_results / budget_results / refs).
        # NOTE: `query` (SQL incl. WHERE-clause PII) and `detail` (raw observed DB values) are
        # DELIBERATELY NOT here — they are masked by default per FEATURE-SPEC §11 / DEVELOPMENT §28
        # and only emitted when the operator opts in via `redaction.allow_fields`. The safe
        # structural fields below convey which check ran and its outcome without any row data.
        "ok",
        "present",
        "comparator",
        "kind",
        "fired",
        "gating",
        "max_steps",
        "max_cost_usd",
        "max_seconds",
        "measured_seconds",
        "over_budget",
        "agent_claimed_done",
        # nested config dict keys (statistics_config / settlement_config)
        "trials",
        "min_valid_trials",
        "max_error_rate",
        "max_skip_rate",
        "queue",
        "timeout_s",
        "max_wait_s",
    }
)


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(s in k for s in _SENSITIVE)


def _allowed(key: str, allow: frozenset[str]) -> bool:
    # Default-deny: the key must be on the allowlist AND must not look like a secret.
    return key in allow and not _is_sensitive(key)


def _walk(obj: Any, allow: frozenset[str]) -> Any:
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return obj
    if isinstance(obj, str):
        return obj[:_MAX_STR] + "...<truncated>" if len(obj) > _MAX_STR else obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return _walk(asdict(obj), allow)
    if isinstance(obj, dict) or hasattr(obj, "items"):  # dict / Mapping / MappingProxyType
        return {
            str(k): (_walk(v, allow) if _allowed(str(k), allow) else MASK) for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple, set, frozenset)):
        # A scalar STRING inside a list has no key to gate it, so default-deny it (a list of
        # dicts/lists still recurses and is key-gated element-by-element). Numbers/bools/None are
        # non-secret-bearing and kept so structural lists stay legible.
        out: list[Any] = []
        for v in obj:
            if isinstance(v, str) and not isinstance(v, Enum):
                out.append(MASK)
            else:
                out.append(_walk(v, allow))
        return out
    return str(obj)


def redact(obj: Any, *, allow_fields: Iterable[str] = ()) -> Any:
    """Fail-closed allowlist redaction: emit only allowlisted keys, mask everything else.

    `allow_fields` is the operator's per-app widening (config `redaction.allow_fields`).
    """
    allow = _DEFAULT_ALLOW | frozenset(allow_fields)
    return _walk(obj, allow)


def json_safe(obj: Any) -> Any:
    """Allowlist-redacted, JSON-serializable evidence (default allowlist only).

    Retained as the default entry point; `redact(obj, allow_fields=...)` widens it per app.
    """
    return redact(obj)
