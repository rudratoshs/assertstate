"""Load + validate `assertstate.yaml` into a typed AssertStateConfig (DEVELOPMENT.md §6).

Secret refs use `env:VAR`; they are resolved at load from the environment and never persisted.
Fail-closed: a missing env var, missing required field, or non-allowlist redaction mode is a
load error (a run never starts on a bad config). Read-only verification of the oracle role is
performed at run setup (ConfiguredEnvironment), not here, so config loading stays DB-free.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from assertstate.config.model import (
    AppConfig,
    AssertStateConfig,
    BrowserConfig,
    EnvironmentConfig,
    OracleConfig,
)

# shared => observed (db_delta non-gating). reset_hook / template_restore => causal, and each
# requires a per-trial reset_cmd that re-establishes single-writer isolation (DEVELOPMENT §6, §20).
_VALID_STRATEGIES = {"shared", "reset_hook", "template_restore"}
_CAUSAL_STRATEGIES = {"reset_hook", "template_restore"}


class ConfigError(Exception):
    """assertstate.yaml could not be loaded/validated. -> CLI failure, no run."""


def _resolve(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{where}: expected a string, got {type(value).__name__}")
    if value.startswith("env:"):
        var = value[4:]
        resolved = os.environ.get(var)
        if not resolved:
            raise ConfigError(f"{where}: env var {var!r} is not set")
        return resolved
    return value


def _app(name: str, raw: dict[str, Any]) -> AppConfig:
    where = f"apps.{name}"
    if "oracle" not in raw or "db_dsn" not in raw["oracle"]:
        raise ConfigError(f"{where}.oracle.db_dsn: required (read-only DSN)")
    if "browser" not in raw or "base_url" not in raw["browser"]:
        raise ConfigError(f"{where}.browser.base_url: required")

    orc = raw["oracle"]
    oracle = OracleConfig(
        db_dsn=_resolve(orc["db_dsn"], f"{where}.oracle.db_dsn"),
        api_base=str(orc["api_base"]) if orc.get("api_base") else None,
        api_creds=(
            _resolve(orc["api_creds_ref"], f"{where}.oracle.api_creds_ref")
            if orc.get("api_creds_ref")
            else None
        ),
    )
    b = raw["browser"]
    creds = _resolve(b["creds_ref"], f"{where}.browser.creds_ref") if "creds_ref" in b else None
    capture = str(b.get("capture", "auto"))
    if capture not in ("auto", "on", "off"):
        raise ConfigError(f"{where}.browser.capture: must be auto|on|off, got {capture!r}")
    # Optional remote cloud-browser CDP endpoint: literal `cdp_url` or secret `cdp_url_ref`.
    if "cdp_url_ref" in b:
        cdp_url: str | None = _resolve(b["cdp_url_ref"], f"{where}.browser.cdp_url_ref")
    elif "cdp_url" in b:
        cdp_url = str(b["cdp_url"])
    else:
        cdp_url = None
    browser = BrowserConfig(
        base_url=str(b["base_url"]), creds=creds, capture=capture, cdp_url=cdp_url
    )

    env_raw = raw.get("environment", {}) or {}
    strategy = str(env_raw.get("strategy", "shared"))
    if strategy not in _VALID_STRATEGIES:
        raise ConfigError(
            f"{where}.environment.strategy: unknown {strategy!r} ({_VALID_STRATEGIES})"
        )
    reset_cmd = env_raw.get("reset_cmd") or env_raw.get("reset_hook")
    if strategy in _CAUSAL_STRATEGIES and not reset_cmd:
        raise ConfigError(
            f"{where}.environment: {strategy} strategy requires a reset_cmd that restores "
            "per-trial single-writer isolation (AssertState does not provision an external DB)"
        )
    environment = EnvironmentConfig(strategy=strategy, reset_cmd=reset_cmd)

    adapter_env = {
        k: _resolve(v, f"{where}.adapter_env.{k}")
        for k, v in (raw.get("adapter_env") or {}).items()
    }
    return AppConfig(
        name=name, oracle=oracle, browser=browser, environment=environment, adapter_env=adapter_env
    )


def load_config(path: str | Path) -> AssertStateConfig:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"config: cannot read {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"config: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("apps"), dict) or not raw["apps"]:
        raise ConfigError("config: top level must have a non-empty `apps` mapping")

    # `statistics` is per-contract and has no safe default (schema.py) — reject it here fail-closed
    # rather than silently ignore a config-level block the operator might expect to apply.
    if "statistics" in raw:
        raise ConfigError(
            "config: `statistics` belongs in the contract, not assertstate.yaml — "
            "trials + pass_threshold have no safe default and are per-contract"
        )

    redaction = raw.get("redaction") or {}
    redaction_mode = str(redaction.get("mode", "allowlist"))
    if redaction_mode != "allowlist":
        raise ConfigError("redaction.mode must be 'allowlist' (fail-closed default)")
    allow_raw = redaction.get("allow_fields", [])
    if not isinstance(allow_raw, list) or not all(isinstance(x, str) for x in allow_raw):
        raise ConfigError("redaction.allow_fields must be a list of field-name strings")

    apps = {name: _app(name, body or {}) for name, body in raw["apps"].items()}
    return AssertStateConfig(
        apps=apps,
        redaction_mode=redaction_mode,
        redaction_allow_fields=tuple(allow_raw),
        canonicalizer=str(raw.get("canonicalizer", "canon-v1")),
    )
