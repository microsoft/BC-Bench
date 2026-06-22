"""Tests for counterfactual consistency, correctness drop, and structural metrics."""

import pytest

from bcbench.analysis.family import FamilyOutcome, InstanceResult
from bcbench.analysis.metrics import (
    Consistency,
    classify_consistency,
    consistency_distribution,
    correctness_drop,
)
from bcbench.analysis.sensitivity import (
    CounterfactualPatchPair,
    Reaction,
    build_patch_pairs,
    mean_sensitivity,
    median_sensitivity,
    patch_distance,
    reaction_distribution,
    sensitivity_score,
    structural_distance,
)


def _inst(instance_id: str, *, is_base: bool, passed: bool) -> InstanceResult:
    return InstanceResult(instance_id=instance_id, is_base=is_base, compiled=True, passed=passed)


def _family(family_id: str, base_passed: bool, cf_passed: list[bool]) -> FamilyOutcome:
    base = _inst(family_id, is_base=True, passed=base_passed)
    cfs = tuple(_inst(f"{family_id}__cf-{i + 1}", is_base=False, passed=p) for i, p in enumerate(cf_passed))
    return FamilyOutcome(family_id=family_id, failure_layer=None, base=base, cfs=cfs)


class TestClassifyConsistency:
    def test_both_correct(self):
        assert classify_consistency(True, True) == Consistency.BOTH_CORRECT

    def test_base_correct_cf_incorrect(self):
        assert classify_consistency(True, False) == Consistency.BASE_CORRECT_CF_INCORRECT

    def test_both_incorrect(self):
        assert classify_consistency(False, False) == Consistency.BOTH_INCORRECT

    def test_base_incorrect_cf_correct(self):
        assert classify_consistency(False, True) == Consistency.BASE_INCORRECT_CF_CORRECT


class TestConsistencyDistribution:
    def test_counts_over_pairs(self):
        families = [
            _family("F1", True, [True, False]),  # both-correct + base-correct-cf-incorrect
            _family("F2", False, [True, False]),  # base-incorrect-cf-correct + both-incorrect
        ]
        dist = consistency_distribution(families)
        assert dist[Consistency.BOTH_CORRECT.value] == 1
        assert dist[Consistency.BASE_CORRECT_CF_INCORRECT.value] == 1
        assert dist[Consistency.BASE_INCORRECT_CF_CORRECT.value] == 1
        assert dist[Consistency.BOTH_INCORRECT.value] == 1

    def test_all_buckets_present_even_when_zero(self):
        dist = consistency_distribution([_family("F1", True, [True])])
        assert set(dist) == {c.value for c in Consistency}
        assert dist[Consistency.BOTH_INCORRECT.value] == 0

    def test_sum_equals_pair_count(self):
        families = [_family("F1", True, [True, False, False]), _family("F2", False, [True])]
        dist = consistency_distribution(families)
        assert sum(dist.values()) == 4


class TestCorrectnessDrop:
    def test_pair_level_fraction(self):
        # base-correct CF pairs: F1 has 2 (1 fail), F2 has 1 (0 fail). 1/3.
        families = [_family("F1", True, [True, False]), _family("F2", True, [True])]
        assert correctness_drop(families) == pytest.approx(1 / 3)

    def test_ignores_base_failures(self):
        families = [_family("F1", False, [False, True])]
        assert correctness_drop(families) == 0.0

    def test_all_cf_fail(self):
        assert correctness_drop([_family("F1", True, [False, False])]) == 1.0

    def test_differs_from_family_level(self):
        # One family, base passes, 1 of 3 CFs fail: correctness_drop is 1/3 (pair-level),
        # not 1.0 that family-level fragility would give for this fragile family.
        assert correctness_drop([_family("F1", True, [True, True, False])]) == pytest.approx(1 / 3)


class TestStructuralDistance:
    def test_identical_is_zero(self):
        assert structural_distance("a\nb\nc", "a\nb\nc") == 0.0

    def test_both_empty_is_zero(self):
        assert structural_distance("", "") == 0.0

    def test_disjoint_is_one(self):
        assert structural_distance("a\nb", "x\ny") == 1.0

    def test_partial_change_in_range(self):
        d = structural_distance("a\nb\nc\nd", "a\nb\nc\nX")
        assert 0.0 < d < 1.0

    def test_symmetric(self):
        a, b = "a\nb\nc", "a\nX\nc"
        assert structural_distance(a, b) == structural_distance(b, a)


def _pair(
    *,
    base_gold: str,
    cf_gold: str,
    base_out: str,
    cf_out: str,
    base_passed: bool = True,
    cf_passed: bool = True,
) -> CounterfactualPatchPair:
    return CounterfactualPatchPair(
        family_id="F1",
        cf_instance_id="F1__cf-1",
        base_passed=base_passed,
        cf_passed=cf_passed,
        base_gold_test_patch=base_gold,
        cf_gold_test_patch=cf_gold,
        base_output_patch=base_out,
        cf_output_patch=cf_out,
    )


class TestSensitivityScore:
    def test_none_when_spec_unchanged(self):
        pair = _pair(base_gold="a\nb", cf_gold="a\nb", base_out="a\nb", cf_out="x\ny")
        assert sensitivity_score(pair) is None

    def test_proportional_reaction_near_one(self):
        # Spec and output change by the same one-line edit -> ratio ~1.
        pair = _pair(base_gold="a\nb\nc\nd", cf_gold="a\nb\nc\nX", base_out="a\nb\nc\nd", cf_out="a\nb\nc\nX")
        assert sensitivity_score(pair) == pytest.approx(1.0)

    def test_under_reaction_below_one(self):
        # Spec changes a lot, model output barely moves -> S < 1.
        pair = _pair(base_gold="a\nb\nc\nd", cf_gold="w\nx\ny\nz", base_out="a\nb\nc\nd", cf_out="a\nb\nc\nd")
        assert sensitivity_score(pair) == pytest.approx(0.0)

    def test_over_reaction_above_one(self):
        # Spec barely changes, model rewrites everything -> S > 1.
        pair = _pair(base_gold="a\nb\nc\nd", cf_gold="a\nb\nc\nX", base_out="a\nb\nc\nd", cf_out="w\nx\ny\nz")
        assert sensitivity_score(pair) > 1.0


class TestPatchDistance:
    def test_reaction_none_when_spec_unchanged(self):
        pair = _pair(base_gold="a\nb", cf_gold="a\nb", base_out="a\nb", cf_out="x\ny")
        pd = patch_distance(pair)
        assert pd.ratio is None
        assert pd.reaction is None
        assert pd.unrelated_rewrite is False

    def test_under_reaction_label(self):
        pair = _pair(base_gold="a\nb\nc\nd", cf_gold="w\nx\ny\nz", base_out="a\nb\nc\nd", cf_out="a\nb\nc\nd")
        assert patch_distance(pair).reaction == Reaction.UNDER

    def test_appropriate_label(self):
        pair = _pair(base_gold="a\nb\nc\nd", cf_gold="a\nb\nc\nX", base_out="a\nb\nc\nd", cf_out="a\nb\nc\nX")
        assert patch_distance(pair).reaction == Reaction.APPROPRIATE

    def test_over_reaction_label(self):
        pair = _pair(base_gold="a\nb\nc\nd", cf_gold="a\nb\nc\nX", base_out="a\nb\nc\nd", cf_out="w\nx\ny\nz")
        assert patch_distance(pair).reaction == Reaction.OVER

    def test_unrelated_rewrite_flag(self):
        # Over-reaction AND the CF failed -> flagged as unrelated rewrite.
        pair = _pair(
            base_gold="a\nb\nc\nd",
            cf_gold="a\nb\nc\nX",
            base_out="a\nb\nc\nd",
            cf_out="w\nx\ny\nz",
            cf_passed=False,
        )
        assert patch_distance(pair).unrelated_rewrite is True

    def test_over_reaction_but_passed_not_flagged(self):
        pair = _pair(base_gold="a\nb\nc\nd", cf_gold="a\nb\nc\nX", base_out="a\nb\nc\nd", cf_out="w\nx\ny\nz", cf_passed=True)
        assert patch_distance(pair).unrelated_rewrite is False


class TestAggregates:
    def test_mean_sensitivity_skips_unchanged_spec(self):
        pairs = [
            _pair(base_gold="a\nb\nc\nd", cf_gold="a\nb\nc\nX", base_out="a\nb\nc\nd", cf_out="a\nb\nc\nX"),  # ~1
            _pair(base_gold="a\nb", cf_gold="a\nb", base_out="a\nb", cf_out="z"),  # None, skipped
        ]
        assert mean_sensitivity(pairs) == pytest.approx(1.0)

    def test_mean_sensitivity_none_when_all_skipped(self):
        pairs = [_pair(base_gold="a", cf_gold="a", base_out="a", cf_out="b")]
        assert mean_sensitivity(pairs) is None

    def test_median_sensitivity_robust_to_outlier(self):
        # Three appropriate (~1) pairs plus one extreme over-reaction: median stays ~1
        # while the mean is dragged far above 1.
        appropriate = _pair(base_gold="a\nb\nc\nd", cf_gold="a\nb\nc\nX", base_out="a\nb\nc\nd", cf_out="a\nb\nc\nX")
        outlier = _pair(base_gold="a\nb\nc\nd", cf_gold="a\nb\nc\nX", base_out="a\nb\nc\nd", cf_out="w\nx\ny\nz")
        pairs = [appropriate, appropriate, appropriate, outlier]
        med = median_sensitivity(pairs)
        mean = mean_sensitivity(pairs)
        assert med == pytest.approx(1.0)
        assert mean > med

    def test_median_sensitivity_none_when_all_skipped(self):
        pairs = [_pair(base_gold="a", cf_gold="a", base_out="a", cf_out="b")]
        assert median_sensitivity(pairs) is None

    def test_reaction_distribution(self):
        pairs = [
            _pair(base_gold="a\nb\nc\nd", cf_gold="w\nx\ny\nz", base_out="a\nb\nc\nd", cf_out="a\nb\nc\nd"),  # under
            _pair(base_gold="a\nb\nc\nd", cf_gold="a\nb\nc\nX", base_out="a\nb\nc\nd", cf_out="a\nb\nc\nX"),  # appropriate
            _pair(base_gold="a\nb", cf_gold="a\nb", base_out="a\nb", cf_out="z"),  # skipped
        ]
        dist = reaction_distribution(pairs)
        assert dist[Reaction.UNDER.value] == 1
        assert dist[Reaction.APPROPRIATE.value] == 1
        assert dist[Reaction.OVER.value] == 0


class TestBuildPatchPairs:
    def test_pairs_cf_with_base(self):
        generated = {"NAV-1": "base out", "NAV-1__cf-1": "cf out"}
        gold = {"NAV-1": "base gold", "NAV-1__cf-1": "cf gold"}
        passed = {"NAV-1": True, "NAV-1__cf-1": False}
        pairs = build_patch_pairs(generated, gold, passed)
        assert len(pairs) == 1
        p = pairs[0]
        assert p.family_id == "NAV-1"
        assert p.cf_instance_id == "NAV-1__cf-1"
        assert p.base_passed is True
        assert p.cf_passed is False
        assert p.base_output_patch == "base out"
        assert p.cf_gold_test_patch == "cf gold"

    def test_skips_cf_without_base(self):
        generated = {"NAV-1__cf-1": "cf out"}
        gold = {"NAV-1__cf-1": "cf gold"}
        pairs = build_patch_pairs(generated, gold, {})
        assert pairs == []

    def test_ignores_base_only_entries(self):
        pairs = build_patch_pairs({"NAV-1": "x"}, {"NAV-1": "y"}, {"NAV-1": True})
        assert pairs == []
