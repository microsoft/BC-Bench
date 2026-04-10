"""Thesis-specific scorers in Braintrust scorer format."""

from __future__ import annotations


class FamilyFragilityRate:
    """Proportion of families where base passes but at least one CF fails."""

    def __call__(self, *, metadata: dict, **kwargs) -> bool:
        return metadata.get("fragile", False)


class FamilySeverity:
    """Fraction of CFs that fail within a family (0.0-1.0)."""

    def __call__(self, *, metadata: dict, **kwargs) -> float | None:
        return metadata.get("severity")


class FamilyStability:
    """Whether all instances in a family (base + CFs) pass."""

    def __call__(self, *, metadata: dict, **kwargs) -> bool:
        return metadata.get("stable", False)
