"""Analysis module for family-level counterfactual evaluation."""

from bcbench.analysis.aggregator import build_families
from bcbench.analysis.family import FamilyOutcome, FamilyType, InstanceResult
from bcbench.analysis.metrics import (
    Consistency,
    cf_exposed_failure_count,
    classify_consistency,
    consistency_distribution,
    correctness_drop,
    failure_layer_distribution,
    family_type_distribution,
    fragility_rate,
    layer_conditioned_fragility,
    mean_severity,
)
from bcbench.analysis.sensitivity import (
    CounterfactualPatchPair,
    PatchDistance,
    Reaction,
    build_patch_pairs,
    mean_sensitivity,
    median_sensitivity,
    patch_distance,
    reaction_distribution,
    sensitivity_score,
    structural_distance,
)

__all__ = [
    "Consistency",
    "CounterfactualPatchPair",
    "FamilyOutcome",
    "FamilyType",
    "InstanceResult",
    "PatchDistance",
    "Reaction",
    "build_families",
    "build_patch_pairs",
    "cf_exposed_failure_count",
    "classify_consistency",
    "consistency_distribution",
    "correctness_drop",
    "failure_layer_distribution",
    "family_type_distribution",
    "fragility_rate",
    "layer_conditioned_fragility",
    "mean_sensitivity",
    "mean_severity",
    "median_sensitivity",
    "patch_distance",
    "reaction_distribution",
    "sensitivity_score",
    "structural_distance",
]
