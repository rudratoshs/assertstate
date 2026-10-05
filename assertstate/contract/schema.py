"""Structural (shape) validation of a raw contract dict (FEATURE-SPEC §2.1).

Returns a list of error strings; empty means the shape is well-formed enough to
attempt typed construction in loader.py. Deeper, cross-field rules live in semantic.py.
"""

from __future__ import annotations

from typing import Any

TOP_LEVEL_KEYS = {
    "task",
    "app",
    "expect",
    "forbid",
    "budget",
    "statistics",
    "preconditions",
    "trajectory",
}


def validate_schema(raw: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(raw, dict):
        return ["contract: top level must be a mapping"]

    for key in ("task", "app"):
        if not raw.get(key) or not isinstance(raw.get(key), str):
            errors.append(f"contract: `{key}` is required and must be a non-empty string")

    unknown = set(raw) - TOP_LEVEL_KEYS
    if unknown:
        errors.append(f"contract: unknown top-level keys {sorted(unknown)}")

    for section in ("expect", "forbid", "preconditions", "trajectory"):
        if section in raw and not isinstance(raw[section], list):
            errors.append(f"contract.{section}: must be a list")

    if "budget" in raw and not isinstance(raw["budget"], dict):
        errors.append("contract.budget: must be a mapping")

    stats = raw.get("statistics")
    if stats is None:
        errors.append(
            "contract.statistics: required (trials + pass_threshold have no safe default)"
        )
    elif not isinstance(stats, dict):
        errors.append("contract.statistics: must be a mapping")
    else:
        for key in ("trials", "pass_threshold"):
            if key not in stats:
                errors.append(f"contract.statistics.{key}: required")

    return errors
