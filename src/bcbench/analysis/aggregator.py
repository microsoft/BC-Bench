"""Aggregate instance-level results into family-level outcomes."""

from __future__ import annotations

import re
from collections import defaultdict

from bcbench.analysis.family import FamilyOutcome, InstanceResult
from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.types import FailureLayer

_CF_PATTERN = re.compile(r"^(.+)__cf-\d+$")


def _extract_base_id(instance_id: str) -> str | None:
    m = _CF_PATTERN.match(instance_id)
    return m.group(1) if m else None


def build_families(
    results: list[ExecutionBasedEvaluationResult],
    failure_layers: dict[str, FailureLayer] | None = None,
) -> list[FamilyOutcome]:
    """Group results into families and compute family-level outcomes.

    Args:
        results: All instance-level results (base + CF) for a single model run.
        failure_layers: Optional map of base_instance_id -> FailureLayer.
    """
    if failure_layers is None:
        failure_layers = {}

    base_results: dict[str, ExecutionBasedEvaluationResult] = {}
    cf_results: dict[str, list[ExecutionBasedEvaluationResult]] = defaultdict(list)

    for result in results:
        base_id = _extract_base_id(result.instance_id)
        if base_id is not None:
            cf_results[base_id].append(result)
        else:
            base_results[result.instance_id] = result

    families: list[FamilyOutcome] = []
    for base_id, base_result in base_results.items():
        cfs = cf_results.get(base_id, [])
        if not cfs:
            continue

        base_inst = InstanceResult(
            instance_id=base_result.instance_id,
            is_base=True,
            compiled=base_result.build,
            passed=base_result.resolved,
        )

        cf_insts = tuple(
            InstanceResult(
                instance_id=cf.instance_id,
                is_base=False,
                compiled=cf.build,
                passed=cf.resolved,
            )
            for cf in sorted(cfs, key=lambda c: c.instance_id)
        )

        families.append(
            FamilyOutcome(
                family_id=base_id,
                failure_layer=failure_layers.get(base_id),
                base=base_inst,
                cfs=cf_insts,
            )
        )

    return sorted(families, key=lambda f: f.family_id)
