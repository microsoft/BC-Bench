"""Structural-change metrics for counterfactual sensitivity analysis.

These metrics compare, for each base->CF pair, how much the *specification* changed
against how much the *model's generated patch* changed. They answer Exp 2 questions
that pass/fail metrics cannot: did the model react to the requirement shift, and did
it react by the right amount?

- Sensitivity Score: ``S = output_delta / spec_delta``. S~1 means the model adjusted
  its solution in proportion to the spec change; S<<1 is under-reaction (ignored the
  shift); S>>1 is over-reaction (rewrote far more than the shift demanded).
- Patch Distance: exposes the raw component distances plus a direction label and an
  ``unrelated_rewrite`` flag, so a notebook can judge under/over-reaction directly.

Structural distance is line-based (patches are line-oriented) and uses only the
standard library, so no edit-distance dependency is required.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from enum import StrEnum
from statistics import median

__all__ = [
    "CounterfactualPatchPair",
    "PatchDistance",
    "Reaction",
    "build_patch_pairs",
    "mean_sensitivity",
    "median_sensitivity",
    "patch_distance",
    "reaction_distribution",
    "sensitivity_score",
    "structural_distance",
]

_CF_PATTERN = re.compile(r"^(.+)__cf-\d+$")

#: Half-width of the multiplicative band (around S=1) treated as "appropriate".
#: With 0.5, S in [0.5, 1.5] is appropriate, below is under-, above is over-reaction.
DEFAULT_TOLERANCE = 0.5


class Reaction(StrEnum):
    UNDER = "under-reaction"
    APPROPRIATE = "appropriate"
    OVER = "over-reaction"


def structural_distance(a: str, b: str) -> float:
    """Normalized line-level distance in [0, 1] (0 = identical, 1 = disjoint)."""
    a_lines = a.splitlines()
    b_lines = b.splitlines()
    if not a_lines and not b_lines:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a_lines, b_lines).ratio()
    return 1.0 - ratio


@dataclass(frozen=True)
class CounterfactualPatchPair:
    """A base->CF pair carrying both gold (spec) and model-generated patches."""

    family_id: str
    cf_instance_id: str
    base_passed: bool
    cf_passed: bool
    base_gold_test_patch: str
    cf_gold_test_patch: str
    base_output_patch: str
    cf_output_patch: str

    @property
    def spec_delta(self) -> float:
        """How much the requirement moved, from the gold CF test patches."""
        return structural_distance(self.base_gold_test_patch, self.cf_gold_test_patch)

    @property
    def output_delta(self) -> float:
        """How much the model moved its own solution between base and CF."""
        return structural_distance(self.base_output_patch, self.cf_output_patch)


@dataclass(frozen=True)
class PatchDistance:
    """Diagnostic breakdown of a pair's reaction to the spec change."""

    spec_delta: float
    output_delta: float
    ratio: float | None
    reaction: Reaction | None
    unrelated_rewrite: bool


def sensitivity_score(pair: CounterfactualPatchPair) -> float | None:
    """``output_delta / spec_delta``; None when the spec did not change."""
    spec = pair.spec_delta
    if spec <= 0.0:
        return None
    return pair.output_delta / spec


def patch_distance(pair: CounterfactualPatchPair, tolerance: float = DEFAULT_TOLERANCE) -> PatchDistance:
    """Component distances plus reaction direction and unrelated-rewrite flag.

    ``unrelated_rewrite`` flags over-reactions that broke the CF: the model rewrote
    far more than the shift demanded *and* the CF still failed, a signature of edits
    unrelated to the requirement change.
    """
    spec = pair.spec_delta
    output = pair.output_delta
    ratio = sensitivity_score(pair)

    reaction: Reaction | None
    if ratio is None:
        reaction = None
    elif ratio < 1.0 - tolerance:
        reaction = Reaction.UNDER
    elif ratio > 1.0 + tolerance:
        reaction = Reaction.OVER
    else:
        reaction = Reaction.APPROPRIATE

    unrelated_rewrite = reaction == Reaction.OVER and not pair.cf_passed
    return PatchDistance(
        spec_delta=spec,
        output_delta=output,
        ratio=ratio,
        reaction=reaction,
        unrelated_rewrite=unrelated_rewrite,
    )


def mean_sensitivity(pairs: list[CounterfactualPatchPair]) -> float | None:
    """Mean sensitivity score over pairs whose spec actually changed.

    The mean is sensitive to outliers: when the spec barely moves (small
    ``spec_delta``) the ratio explodes, so prefer `median_sensitivity` or
    `reaction_distribution` as the robust headline.
    """
    scores = [s for p in pairs if (s := sensitivity_score(p)) is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)


def median_sensitivity(pairs: list[CounterfactualPatchPair]) -> float | None:
    """Median sensitivity score; robust to the heavy right skew of the ratio."""
    scores = [s for p in pairs if (s := sensitivity_score(p)) is not None]
    if not scores:
        return None
    return median(scores)


def reaction_distribution(pairs: list[CounterfactualPatchPair], tolerance: float = DEFAULT_TOLERANCE) -> dict[str, int]:
    """Count of under-/appropriate/over-reaction pairs (spec-unchanged pairs skipped)."""
    counts = {r.value: 0 for r in Reaction}
    for pair in pairs:
        reaction = patch_distance(pair, tolerance).reaction
        if reaction is not None:
            counts[reaction.value] += 1
    return counts


def build_patch_pairs(
    generated_patches: dict[str, str],
    gold_test_patches: dict[str, str],
    passed: dict[str, bool],
) -> list[CounterfactualPatchPair]:
    """Assemble base->CF pairs from per-instance lookups.

    Args:
        generated_patches: instance_id -> model output patch (the result ``output``).
        gold_test_patches: instance_id -> gold ``test_patch`` from the dataset.
        passed: instance_id -> whether the instance resolved.

    Only CF instances whose base instance is present in all three lookups are paired.
    """
    pairs: list[CounterfactualPatchPair] = []
    for cf_id in sorted(generated_patches):
        m = _CF_PATTERN.match(cf_id)
        if m is None:
            continue
        base_id = m.group(1)
        if base_id not in generated_patches or base_id not in gold_test_patches or cf_id not in gold_test_patches:
            continue
        pairs.append(
            CounterfactualPatchPair(
                family_id=base_id,
                cf_instance_id=cf_id,
                base_passed=passed.get(base_id, False),
                cf_passed=passed.get(cf_id, False),
                base_gold_test_patch=gold_test_patches[base_id],
                cf_gold_test_patch=gold_test_patches[cf_id],
                base_output_patch=generated_patches[base_id],
                cf_output_patch=generated_patches[cf_id],
            )
        )
    return pairs
