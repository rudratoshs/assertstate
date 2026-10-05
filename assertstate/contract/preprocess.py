"""Contract pre-processing (FEATURE-SPEC §3 reusable/templated): `include` policy packs +
`${param}` substitution, applied BEFORE schema/typed construction.

- `include: [rel/path.yaml, ...]` — merge each pack's `forbid`/`expect` entries into the contract
  (included entries FIRST, then the contract's own). A pack is a YAML with `forbid`/`expect` lists.
- `params: {k: v}` + `${k}` placeholders in any STRING scalar — substituted; an undefined `${k}`
  is a ContractError (fail-closed; never a half-substituted query).

Safety (a NEW file-read surface): include paths must be relative and resolve to a real file UNDER
the including file's directory (no absolute paths, no `..` escape); include depth is capped and
cycles rejected. `include`/`params` are consumed here, so the merged dict carries neither and
passes the existing schema unchanged.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from assertstate.contract.errors import ContractError

_MAX_INCLUDE_DEPTH = 5
_PARAM_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _safe_include_path(base_dir: Path, inc: str, where: str) -> Path:
    if not isinstance(inc, str) or not inc:
        raise ContractError(f"{where}: include entries must be non-empty strings")
    p = Path(inc)
    if p.is_absolute():
        raise ContractError(f"{where}: include path must be relative, got {inc!r}")
    resolved = (base_dir / p).resolve()
    root = base_dir.resolve()
    if root != resolved and root not in resolved.parents:
        raise ContractError(f"{where}: include {inc!r} escapes the contract directory")
    if not resolved.is_file():
        raise ContractError(f"{where}: include not found: {inc!r}")
    return resolved


def _substitute(obj: Any, params: dict[str, Any], where: str) -> Any:
    if isinstance(obj, str):

        def repl(m: re.Match[str]) -> str:
            name = m.group(1)
            if name not in params:
                raise ContractError(f"{where}: undefined ${{{name}}} (not in params)")
            return str(params[name])

        return _PARAM_RE.sub(repl, obj)
    if isinstance(obj, dict):
        return {k: _substitute(v, params, where) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute(v, params, where) for v in obj]
    return obj


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"contract not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ContractError(f"invalid YAML in {path.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContractError(f"{path.name}: top level must be a mapping")
    return raw


def _preprocess(
    path: Path, params_override: dict[str, Any], seen: frozenset[Path], depth: int
) -> dict[str, Any]:
    if depth > _MAX_INCLUDE_DEPTH:
        raise ContractError(f"include depth exceeded ({_MAX_INCLUDE_DEPTH})")
    real = path.resolve()
    if real in seen:
        raise ContractError(f"include cycle detected at {path.name}")
    seen = seen | {real}

    raw = _load_yaml(path)
    params = {**(raw.get("params") or {}), **params_override}

    merged_forbid: list[Any] = []
    merged_expect: list[Any] = []
    includes = raw.get("include") or []
    if not isinstance(includes, list):
        raise ContractError(f"{path.name}.include: must be a list of path strings")
    for inc in includes:
        inc_path = _safe_include_path(path.parent, inc, f"{path.name}.include")
        pack = _preprocess(inc_path, params, seen, depth + 1)
        merged_forbid += list(pack.get("forbid") or [])
        merged_expect += list(pack.get("expect") or [])

    out = {k: v for k, v in raw.items() if k not in ("include", "params")}
    # Included entries first, then the contract's own (documented order).
    if merged_forbid or "forbid" in raw:
        out["forbid"] = merged_forbid + list(raw.get("forbid") or [])
    if merged_expect or "expect" in raw:
        out["expect"] = merged_expect + list(raw.get("expect") or [])
    result = _substitute(out, params, path.name)
    assert isinstance(result, dict)
    return result


def preprocess(path: str | Path) -> dict[str, Any]:
    """Resolve includes + substitute params; return the merged contract dict (no include/params)."""
    return _preprocess(Path(path), {}, frozenset(), 0)
