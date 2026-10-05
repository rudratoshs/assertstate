"""Typed `assertstate.yaml` config model (DEVELOPMENT.md §6; FEATURE-SPEC §14).

Separates TRUSTED oracle config (read-only db_dsn) from agent-visible browser config. The
split is the same trust boundary the runtime enforces: the oracle DSN is never placed on the
BrowserTarget.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OracleConfig:
    db_dsn: str  # resolved read-only DSN (trusted)
    api_base: str | None = None  # read-only API oracle base (for expect.api)
    api_creds: str | None = None  # resolved from api_creds_ref


@dataclass(frozen=True)
class BrowserConfig:
    base_url: str
    creds: str | None = None  # agent-visible; resolved from creds_ref
    # Trusted network capture for http/external/trajectory policies (§3). "auto" (default): on when
    # base_url is plain http:// (capturable without TLS interception), off for https://. "on" forces
    # it (once TLS interception lands, or for an http app behind a scheme-ambiguous url); "off"
    # disables it (those observation-based policies then run NON-GATING, never a false FAIL).
    capture: str = "auto"


@dataclass(frozen=True)
class EnvironmentConfig:
    # "shared" => observed attribution (db_delta non-gating); "reset_hook" => causal via reset_cmd
    strategy: str = "shared"
    reset_cmd: str | None = None


@dataclass(frozen=True)
class AppConfig:
    name: str
    oracle: OracleConfig
    browser: BrowserConfig
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    adapter_env: dict[str, str] = field(default_factory=dict)  # agent creds (e.g. LLM key)


@dataclass(frozen=True)
class AssertStateConfig:
    apps: dict[str, AppConfig]
    statistics_defaults: dict[str, object] = field(default_factory=dict)
    redaction_mode: str = "allowlist"
    redaction_allow_fields: tuple[str, ...] = ()  # operator widening of the evidence allowlist
    canonicalizer: str = "canon-v1"

    def app(self, name: str) -> AppConfig:
        if name not in self.apps:
            raise KeyError(f"app {name!r} not in config (have: {sorted(self.apps)})")
        return self.apps[name]
