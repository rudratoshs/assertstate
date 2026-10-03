"""P0-04 config loader (assertstate.yaml) — pure, no DB/LLM."""

from __future__ import annotations

import tempfile

import pytest
import yaml

from assertstate.config.loader import ConfigError, load_config


def _write(raw: dict) -> str:
    fh = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump(raw, fh)
    fh.close()
    return fh.name


def _base() -> dict:
    return {
        "apps": {
            "staging": {
                "oracle": {"db_dsn": "postgresql://ro@/app"},
                "browser": {"base_url": "https://staging.example.com"},
            }
        }
    }


def test_loads_minimal_config() -> None:
    cfg = load_config(_write(_base()))
    app = cfg.app("staging")
    assert app.oracle.db_dsn == "postgresql://ro@/app"
    assert app.browser.base_url == "https://staging.example.com"
    assert app.environment.strategy == "shared"  # => observed attribution
    assert cfg.redaction_mode == "allowlist"


def test_env_ref_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_RO_DSN", "postgresql://ro@/real")
    monkeypatch.setenv("APP_LOGIN", "user:pw")
    raw = _base()
    raw["apps"]["staging"]["oracle"]["db_dsn"] = "env:APP_RO_DSN"
    raw["apps"]["staging"]["browser"]["creds_ref"] = "env:APP_LOGIN"
    app = load_config(_write(raw)).app("staging")
    assert app.oracle.db_dsn == "postgresql://ro@/real"
    assert app.browser.creds == "user:pw"


def test_missing_env_var_is_error() -> None:
    raw = _base()
    raw["apps"]["staging"]["oracle"]["db_dsn"] = "env:DEFINITELY_NOT_SET_XYZ"
    with pytest.raises(ConfigError, match="not set"):
        load_config(_write(raw))


def test_missing_db_dsn_is_error() -> None:
    raw = _base()
    del raw["apps"]["staging"]["oracle"]["db_dsn"]
    with pytest.raises(ConfigError, match="db_dsn"):
        load_config(_write(raw))


def test_reset_hook_requires_reset_cmd() -> None:
    raw = _base()
    raw["apps"]["staging"]["environment"] = {"strategy": "reset_hook"}
    with pytest.raises(ConfigError, match="reset_cmd"):
        load_config(_write(raw))


def test_non_allowlist_redaction_rejected() -> None:
    raw = _base()
    raw["redaction"] = {"mode": "blocklist"}
    with pytest.raises(ConfigError, match="allowlist"):
        load_config(_write(raw))


def test_unknown_app_raises() -> None:
    cfg = load_config(_write(_base()))
    with pytest.raises(KeyError):
        cfg.app("nope")
