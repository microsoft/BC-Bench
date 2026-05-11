"""Aggregate diagnostic metrics computed across families."""

from __future__ import annotations

from collections import Counter

from bcbench.analysis.family import FamilyOutcome, FamilyType


def family_type_distribution(families: list[FamilyOutcome]) -> dict[str, int]:
    return dict(Counter(f.family_type.value for f in families))


def fragility_rate(families: list[FamilyOutcome]) -> float:
    eligible = [f for f in families if f.base.passed]
    if not eligible:
        return 0.0
    return sum(1 for f in eligible if f.is_fragile) / len(eligible)


def mean_severity(families: list[FamilyOutcome]) -> float | None:
    severities = [f.severity for f in families if f.severity is not None]
    if not severities:
        return None
    return sum(severities) / len(severities)


def layer_conditioned_fragility(families: list[FamilyOutcome]) -> dict[str, float]:
    by_layer: dict[str, list[FamilyOutcome]] = {}
    for f in families:
        if f.failure_layer is None:
            continue
        by_layer.setdefault(f.failure_layer.value, []).append(f)
    return {layer: fragility_rate(fams) for layer, fams in sorted(by_layer.items())}


def failure_layer_distribution(families: list[FamilyOutcome]) -> dict[str, int]:
    counts = Counter(f.failure_layer.value for f in families if f.failure_layer is not None)
    return dict(sorted(counts.items()))


def cf_exposed_failure_count(families: list[FamilyOutcome]) -> int:
    return sum(1 for f in families if f.family_type == FamilyType.FRAGILE and f.cf_fail_count == f.cf_total)
