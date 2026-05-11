"""Analysis module for family-level counterfactual evaluation."""

from bcbench.analysis.aggregator import build_families
from bcbench.analysis.family import FamilyOutcome, FamilyType, InstanceResult
from bcbench.analysis.metrics import (
    cf_exposed_failure_count,
    failure_layer_distribution,
    family_type_distribution,
    fragility_rate,
    layer_conditioned_fragility,
    mean_severity,
)

__all__ = [
    "FamilyOutcome",
    "FamilyType",
    "InstanceResult",
    "build_families",
    "cf_exposed_failure_count",
    "failure_layer_distribution",
    "family_type_distribution",
    "fragility_rate",
    "layer_conditioned_fragility",
    "mean_severity",
]
