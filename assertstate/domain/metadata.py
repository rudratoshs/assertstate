"""RunMetadata provenance + RunManifest (SYSTEM-DESIGN §4, §12; DEVELOPMENT §29).

Unknown values are None, never faked (DEVELOPMENT §29).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunMetadata:
    run_id: str
    assertstate_version: str
    contract_hash: str
    scenario_id: str | None = None
    adapter_name: str | None = None
    adapter_version: str | None = None
    model_provider: str | None = None
    system_prompt_hash: str | None = None
    browser_version: str | None = None
    app_build_git_sha: str | None = None
    db_schema_fingerprint: str | None = None
    fixture_version: str | None = None
    env_image: str | None = None
    canonicalizer_version: str = "canon-v1"
    statistics_config: dict[str, object] = field(default_factory=dict)
    settlement_config: dict[str, object] = field(default_factory=dict)
    timestamp_tz: str | None = None


@dataclass(frozen=True)
class RunManifest:
    """Run configuration — NOT the contract (FEATURE-SPEC §2.4)."""

    targets: tuple[str, ...] = field(default_factory=tuple)
    contracts: tuple[str, ...] = field(default_factory=tuple)
    statistics_overrides: dict[str, object] | None = None
