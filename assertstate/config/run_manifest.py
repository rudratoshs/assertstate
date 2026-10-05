"""Run/matrix manifest loader — `assertstate.run.yaml` (FEATURE-SPEC §2.4).

A run manifest is NOT a contract: it is run configuration that fans a set of contracts across a
set of execution adapters (`targets`). The contract stays framework-neutral; adapter choice lives
here (or on the `--adapter` CLI flag). Shape:

    targets: [browser-use, stagehand, playwright-mcp]   # run-time execution adapters
    contracts: ["contracts/*.yaml"]                       # globs, resolved relative to `base`
"""

from __future__ import annotations

from pathlib import Path

import yaml

from assertstate.contract.errors import ContractError
from assertstate.domain.metadata import RunManifest


def load_run_manifest(path: str | Path) -> RunManifest:
    """Parse + validate a run manifest. Fail-closed: a bad manifest raises ContractError."""
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"run manifest not found: {p}") from exc
    except yaml.YAMLError as exc:
        raise ContractError(f"run manifest: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContractError("run manifest: top level must be a mapping")

    targets = raw.get("targets")
    if not isinstance(targets, list) or not targets or not all(isinstance(t, str) for t in targets):
        raise ContractError("run manifest: `targets` must be a non-empty list of adapter names")
    contracts = raw.get("contracts")
    if (
        not isinstance(contracts, list)
        or not contracts
        or not all(isinstance(c, str) for c in contracts)
    ):
        raise ContractError("run manifest: `contracts` must be a non-empty list of path globs")
    overrides = raw.get("statistics")
    if overrides is not None and not isinstance(overrides, dict):
        raise ContractError("run manifest: `statistics` must be a mapping if present")

    return RunManifest(
        targets=tuple(targets),
        contracts=tuple(contracts),
        statistics_overrides=overrides,
    )


def resolve_contracts(manifest: RunManifest, base: str | Path) -> list[Path]:
    """Expand the manifest's contract globs (relative to `base`) into a sorted, de-duped file list.

    Fail-closed: a glob that matches nothing raises ContractError (never a silent empty matrix).
    """
    base_dir = Path(base)
    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in manifest.contracts:
        matches = sorted(base_dir.glob(pattern))
        if not matches:
            raise ContractError(f"run manifest: contract glob matched no files: {pattern!r}")
        for m in matches:
            if m not in seen and m.is_file():
                seen.add(m)
                found.append(m)
    if not found:
        raise ContractError("run manifest: no contracts resolved")
    return found
