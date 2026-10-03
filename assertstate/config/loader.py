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

_VALID_STRATEGIES = {"shared", "reset_hook"}


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

    oracle = OracleConfig(db_dsn=_resolve(raw["oracle"]["db_dsn"], f"{where}.oracle.db_dsn"))
    b = raw["browser"]
    creds = _resolve(b["creds_ref"], f"{where}.browser.creds_ref") if "creds_ref" in b else None
    browser = BrowserConfig(base_url=str(b["base_url"]), creds=creds)

    env_raw = raw.get("environment", {}) or {}
    strategy = str(env_raw.get("strategy", "shared"))
    if strategy not in _VALID_STRATEGIES:
        raise ConfigError(
            f"{where}.environment.strategy: unknown {strategy!r} ({_VALID_STRATEGIES})"
        )
    if strategy == "reset_hook" and not env_raw.get("reset_cmd"):
        raise ConfigError(f"{where}.environment: reset_hook strategy requires a reset_cmd")
    environment = EnvironmentConfig(strategy=strategy, reset_cmd=env_raw.get("reset_cmd"))

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

    redaction_mode = str((raw.get("redaction") or {}).get("mode", "allowlist"))
    if redaction_mode != "allowlist":
        raise ConfigError("redaction.mode must be 'allowlist' (fail-closed default)")

    apps = {name: _app(name, body or {}) for name, body in raw["apps"].items()}
    return AssertStateConfig(
        apps=apps,
        statistics_defaults=raw.get("statistics") or {},
        redaction_mode=redaction_mode,
        canonicalizer=str(raw.get("canonicalizer", "canon-v1")),
    )
