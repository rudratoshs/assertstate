"""Validation reporting for the contract layer."""

from __future__ import annotations

from dataclasses import dataclass, field


class ContractError(Exception):
    """Raised when a contract cannot be loaded/validated into an executable Contract."""


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, other: "ValidationReport") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
