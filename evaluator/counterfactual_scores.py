"""Counterfactual evaluation scorers in Braintrust scorer format."""

from __future__ import annotations


class FamilyFragilityRate:
    def __call__(self, *, metadata: dict, **kwargs) -> bool:
        return metadata.get("fragile", False)


class FamilySeverity:
    def __call__(self, *, metadata: dict, **kwargs) -> float | None:
        return metadata.get("severity")


class FamilyStability:
    def __call__(self, *, metadata: dict, **kwargs) -> bool:
        return metadata.get("stable", False)
