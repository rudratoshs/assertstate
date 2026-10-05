"""Run/matrix manifest loader + `assertstate matrix` validation (FEATURE-SPEC §2.4)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from assertstate.cli import main
from assertstate.config.run_manifest import load_run_manifest, resolve_contracts
from assertstate.contract.errors import ContractError
from assertstate.domain.metadata import RunManifest

REPO = Path(__file__).resolve().parents[2]


def _write(raw: object) -> str:
    fh = tempfile.NamedTemporaryFile("w", suffix=".run.yaml", delete=False)
    yaml.safe_dump(raw, fh)
    fh.close()
    return fh.name


def test_loads_valid_manifest() -> None:
    m = load_run_manifest(_write({"targets": ["demo", "noop"], "contracts": ["contracts/*.yaml"]}))
    assert isinstance(m, RunManifest)
    assert m.targets == ("demo", "noop") and m.contracts == ("contracts/*.yaml",)


@pytest.mark.parametrize(
    "raw",
    [
        {"contracts": ["contracts/*.yaml"]},  # no targets
        {"targets": [], "contracts": ["x"]},  # empty targets
        {"targets": ["demo"]},  # no contracts
        {"targets": ["demo"], "contracts": []},  # empty contracts
        {"targets": "demo", "contracts": ["x"]},  # targets not a list
        ["not", "a", "mapping"],  # top-level not a mapping
    ],
)
def test_bad_manifest_rejected(raw: object) -> None:
    with pytest.raises(ContractError):
        load_run_manifest(_write(raw))


def test_resolve_contracts_globs_and_dedups() -> None:
    m = RunManifest(
        targets=("demo",), contracts=("contracts/seeds/*.yaml", "contracts/seeds/04-*.yaml")
    )
    files = resolve_contracts(m, REPO)
    assert files and all(f.suffix == ".yaml" for f in files)
    assert len(files) == len(set(files))  # de-duped despite overlapping globs


def test_resolve_contracts_no_match_is_error() -> None:
    m = RunManifest(targets=("demo",), contracts=("contracts/does-not-exist-*.yaml",))
    with pytest.raises(ContractError, match="matched no files"):
        resolve_contracts(m, REPO)


def test_matrix_cli_rejects_unknown_target() -> None:
    mf = _write(
        {"targets": ["demo", "bogus-adapter"], "contracts": ["contracts/pay-invoice.e2e.yaml"]}
    )
    assert main(["matrix", mf, "--app", "demo"]) == 2  # fails before any run


def test_matrix_cli_rejects_bad_manifest() -> None:
    mf = _write({"contracts": ["contracts/pay-invoice.e2e.yaml"]})  # no targets
    assert main(["matrix", mf, "--app", "demo"]) == 2
