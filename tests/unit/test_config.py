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
    assert app.browser.capture == "auto"  # default
    assert cfg.redaction_mode == "allowlist"


def test_capture_field_parsed() -> None:
    raw = _base()
    raw["apps"]["staging"]["browser"]["capture"] = "on"
    assert load_config(_write(raw)).app("staging").browser.capture == "on"


def test_capture_field_rejects_unknown() -> None:
    raw = _base()
    raw["apps"]["staging"]["browser"]["capture"] = "maybe"
    with pytest.raises(ConfigError, match=r"capture: must be auto\|on\|off"):
        load_config(_write(raw))


def test_cdp_url_literal_parsed() -> None:
    raw = _base()
    raw["apps"]["staging"]["browser"]["cdp_url"] = "ws://browser.internal:9222/devtools/browser/x"
    cfg = load_config(_write(raw))
    assert cfg.app("staging").browser.cdp_url == "ws://browser.internal:9222/devtools/browser/x"


def test_cdp_url_ref_resolved_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUD_BROWSER_WSS", "wss://cb.example/devtools?token=sekret")
    raw = _base()
    raw["apps"]["staging"]["browser"]["cdp_url_ref"] = "env:CLOUD_BROWSER_WSS"
    cfg = load_config(_write(raw))
    assert cfg.app("staging").browser.cdp_url == "wss://cb.example/devtools?token=sekret"


def test_cdp_url_default_none() -> None:
    assert load_config(_write(_base())).app("staging").browser.cdp_url is None


def test_config_rejects_top_level_statistics() -> None:
    # statistics is per-contract (no safe default); a config-level block fails closed, not ignored.
    raw = _base()
    raw["statistics"] = {"trials": 20, "pass_threshold": 0.9}
    with pytest.raises(ConfigError, match=r"`statistics` belongs in the contract"):
        load_config(_write(raw))


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


def test_template_restore_is_a_known_strategy() -> None:
    # DEVELOPMENT §6 names template_restore as the P0 strategy; it must load (causal + reset_cmd).
    raw = _base()
    raw["apps"]["staging"]["environment"] = {
        "strategy": "template_restore",
        "reset_cmd": "restore-db.sh",
    }
    app = load_config(_write(raw)).app("staging")
    assert app.environment.strategy == "template_restore"
    assert app.environment.reset_cmd == "restore-db.sh"


def test_template_restore_requires_reset_cmd() -> None:
    raw = _base()
    raw["apps"]["staging"]["environment"] = {"strategy": "template_restore"}
    with pytest.raises(ConfigError, match="reset_cmd"):
        load_config(_write(raw))


def test_unknown_strategy_rejected() -> None:
    raw = _base()
    raw["apps"]["staging"]["environment"] = {"strategy": "voodoo"}
    with pytest.raises(ConfigError, match="unknown"):
        load_config(_write(raw))


def test_redaction_allow_fields_parsed() -> None:
    raw = _base()
    raw["redaction"] = {"mode": "allowlist", "allow_fields": ["notes", "build_id"]}
    cfg = load_config(_write(raw))
    assert cfg.redaction_allow_fields == ("notes", "build_id")


def test_non_allowlist_redaction_rejected() -> None:
    raw = _base()
    raw["redaction"] = {"mode": "blocklist"}
    with pytest.raises(ConfigError, match="allowlist"):
        load_config(_write(raw))


def test_unknown_app_raises() -> None:
    cfg = load_config(_write(_base()))
    with pytest.raises(KeyError):
        cfg.app("nope")
