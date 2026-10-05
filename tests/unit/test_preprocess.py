"""Contract pre-processing (FEATURE-SPEC §3 reusable/templated): include packs + ${param}.

Fixtures are written under pytest's tmp_path (NEVER under contracts/, which the shipped-contract
glob test validates as standalone contracts).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from assertstate.contract.errors import ContractError
from assertstate.contract.preprocess import preprocess


def _w(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


# --------------------------------------------------------------------------- params


def test_param_substitution(tmp_path):
    c = _w(
        tmp_path / "c.yaml",
        "task: t\napp: a\nparams: {tenant: acme}\n"
        'forbid:\n  - touch_other_tenant: {tenant_col: "${tenant}"}\n',
    )
    out = preprocess(c)
    assert "params" not in out
    assert out["forbid"][0]["touch_other_tenant"]["tenant_col"] == "acme"


def test_undefined_param_fails_closed(tmp_path):
    c = _w(tmp_path / "c.yaml", "task: ${nope}\napp: a\n")
    with pytest.raises(ContractError, match=r"undefined \$\{nope\}"):
        preprocess(c)


# -------------------------------------------------------------------------- include


def test_include_merges_packs_first(tmp_path):
    _w(
        tmp_path / "pack.yaml",
        "forbid:\n  - external_request: {}\n",
    )
    c = _w(
        tmp_path / "c.yaml",
        "task: t\napp: a\ninclude: [pack.yaml]\nforbid:\n  - duplicate: {}\n",
    )
    out = preprocess(c)
    assert "include" not in out
    # included entry comes FIRST, then the contract's own
    assert "external_request" in out["forbid"][0]
    assert "duplicate" in out["forbid"][1]


def test_include_rejects_absolute_path(tmp_path):
    c = _w(tmp_path / "c.yaml", "task: t\napp: a\ninclude: [/etc/passwd]\n")
    with pytest.raises(ContractError, match=r"must be relative"):
        preprocess(c)


def test_include_rejects_parent_escape(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    _w(tmp_path / "outside.yaml", "forbid: []\n")
    c = _w(sub / "c.yaml", "task: t\napp: a\ninclude: [../outside.yaml]\n")
    with pytest.raises(ContractError, match=r"escapes the contract directory"):
        preprocess(c)


def test_include_cycle_detected(tmp_path):
    _w(tmp_path / "a.yaml", "include: [b.yaml]\n")
    _w(tmp_path / "b.yaml", "include: [a.yaml]\n")
    c = _w(tmp_path / "c.yaml", "task: t\napp: a\ninclude: [a.yaml]\n")
    with pytest.raises(ContractError, match=r"cycle"):
        preprocess(c)


def test_include_missing_file(tmp_path):
    c = _w(tmp_path / "c.yaml", "task: t\napp: a\ninclude: [nope.yaml]\n")
    with pytest.raises(ContractError, match=r"include not found"):
        preprocess(c)


def test_param_flows_into_included_pack(tmp_path):
    _w(tmp_path / "pack.yaml", 'forbid:\n  - touch_other_tenant: {tenant_col: "${tenant}"}\n')
    c = _w(
        tmp_path / "c.yaml",
        "task: t\napp: a\nparams: {tenant: acme}\ninclude: [pack.yaml]\n",
    )
    out = preprocess(c)
    assert out["forbid"][0]["touch_other_tenant"]["tenant_col"] == "acme"
