"""Aggregate diagnostic metrics computed across families."""

from __future__ import annotations

from collections import Counter
from enum import StrEnum

from bcbench.analysis.family import FamilyOutcome, FamilyType


class Consistency(StrEnum):
    """Four-way counterfactual consistency outcome for a single (base, CF) pair.

    Unlike FamilyType (which summarizes a base + all its CFs), this classifies
    one base instance against one CF instance, so a family with N CFs yields N
    consistency outcomes.
    """

    BOTH_CORRECT = "both-correct"
    BASE_CORRECT_CF_INCORRECT = "base-correct-cf-incorrect"
    BOTH_INCORRECT = "both-incorrect"
    BASE_INCORRECT_CF_CORRECT = "base-incorrect-cf-correct"


def classify_consistency(base_passed: bool, cf_passed: bool) -> Consistency:
    if base_passed and cf_passed:
        return Consistency.BOTH_CORRECT
    if base_passed and not cf_passed:
        return Consistency.BASE_CORRECT_CF_INCORRECT
    if not base_passed and cf_passed:
        return Consistency.BASE_INCORRECT_CF_CORRECT
    return Consistency.BOTH_INCORRECT


def consistency_distribution(families: list[FamilyOutcome]) -> dict[str, int]:
    """Four-way consistency table counted over every (base, CF) pair.

    The four buckets are mutually exclusive and exhaustive:
    both-correct, base-correct-cf-incorrect, both-incorrect, base-incorrect-cf-correct.
    """
    counts: Counter[str] = Counter()
    for family in families:
        for cf in family.cfs:
            counts[classify_consistency(family.base.passed, cf.passed).value] += 1
    return {c.value: counts.get(c.value, 0) for c in Consistency}


def correctness_drop(families: list[FamilyOutcome]) -> float:
    """Pair-level P(CF incorrect | base correct).

    Among all (base, CF) pairs whose base instance passed, the fraction whose CF
    instance failed. This differs from `fragility_rate`: fragility is family-level
    (a family counts once if *any* CF fails), whereas correctness drop is computed
    over individual CF instances.
    """
    eligible = 0
    dropped = 0
    for family in families:
        if not family.base.passed:
            continue
        for cf in family.cfs:
            eligible += 1
            if not cf.passed:
                dropped += 1
    if eligible == 0:
        return 0.0
    return dropped / eligible


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
