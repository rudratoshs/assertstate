"""`assertstate init` scaffolds a usable starter config + contract (no-overwrite)."""

from __future__ import annotations

from pathlib import Path

from assertstate.cli import main
from assertstate.contract.loader import load_and_validate


def test_init_scaffolds_and_contract_validates(tmp_path: Path) -> None:
    assert main(["init", "--dir", str(tmp_path)]) == 0
    cfg = tmp_path / "assertstate.yaml"
    contract = tmp_path / "contracts" / "getting-started.yaml"
    assert cfg.exists() and contract.exists()
    _, report = load_and_validate(contract)
    assert report.ok, report.errors  # the generated contract is valid out of the box


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    assert main(["init", "--dir", str(tmp_path)]) == 0
    assert main(["init", "--dir", str(tmp_path)]) == 2  # second run must not clobber
