"""Tests for family-level evaluation models, aggregation, and metrics."""

import pytest

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
from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.types import EvaluationCategory, FailureLayer


def _inst(instance_id: str, *, is_base: bool, compiled: bool, passed: bool) -> InstanceResult:
    return InstanceResult(instance_id=instance_id, is_base=is_base, compiled=compiled, passed=passed)


def _family(
    family_id: str,
    base_passed: bool,
    cf_passed: list[bool],
    layer: FailureLayer | None = None,
) -> FamilyOutcome:
    base = _inst(family_id, is_base=True, compiled=True, passed=base_passed)
    cfs = tuple(_inst(f"{family_id}__cf-{i + 1}", is_base=False, compiled=True, passed=p) for i, p in enumerate(cf_passed))
    return FamilyOutcome(family_id=family_id, failure_layer=layer, base=base, cfs=cfs)


class TestFamilyOutcome:
    def test_stable_correct_pattern(self):
        f = _family("F1", True, [True, True])
        assert f.pattern == (1, 1, 1)
        assert f.family_type == FamilyType.STABLE_CORRECT
        assert not f.is_fragile
        assert f.severity == 0.0

    def test_fragile_all_cf_fail(self):
        f = _family("F2", True, [False, False])
        assert f.family_type == FamilyType.FRAGILE
        assert f.is_fragile
        assert f.severity == 1.0

    def test_fragile_partial_cf_fail(self):
        f = _family("F3", True, [True, False])
        assert f.family_type == FamilyType.FRAGILE
        assert f.severity == 0.5

    def test_unsolved(self):
        f = _family("F4", False, [False, False])
        assert f.family_type == FamilyType.UNSOLVED
        assert f.severity is None

    def test_inconsistent(self):
        f = _family("F5", False, [True, False])
        assert f.family_type == FamilyType.INCONSISTENT
        assert f.severity is None

    def test_cf_fail_count(self):
        f = _family("F6", True, [True, False, False])
        assert f.cf_fail_count == 2
        assert f.cf_total == 3


class TestBuildFamilies:
    def _result(self, instance_id: str, resolved: bool) -> ExecutionBasedEvaluationResult:
        return ExecutionBasedEvaluationResult(
            instance_id=instance_id,
            project="Test",
            model="test-model",
            agent_name="test",
            category=EvaluationCategory.BUG_FIX,
            resolved=resolved,
            build=True,
        )

    def test_builds_single_family(self):
        results = [
            self._result("NAV-100", True),
            self._result("NAV-100__cf-1", False),
            self._result("NAV-100__cf-2", True),
        ]
        families = build_families(results)
        assert len(families) == 1
        assert families[0].pattern == (1, 0, 1)
        assert families[0].family_type == FamilyType.FRAGILE

    def test_skips_base_without_cfs(self):
        results = [self._result("NAV-200", True)]
        assert len(build_families(results)) == 0

    def test_multiple_families(self):
        results = [
            self._result("NAV-100", True),
            self._result("NAV-100__cf-1", True),
            self._result("NAV-200", False),
            self._result("NAV-200__cf-1", False),
        ]
        families = build_families(results)
        assert len(families) == 2
        assert families[0].family_type == FamilyType.STABLE_CORRECT
        assert families[1].family_type == FamilyType.UNSOLVED

    def test_failure_layers_applied(self):
        results = [
            self._result("NAV-100", True),
            self._result("NAV-100__cf-1", False),
        ]
        families = build_families(results, failure_layers={"NAV-100": FailureLayer.L3_EVENT})
        assert families[0].failure_layer == FailureLayer.L3_EVENT


class TestMetrics:
    @pytest.fixture
    def sample_families(self) -> list[FamilyOutcome]:
        return [
            _family("F1", True, [True, True], FailureLayer.L2_EXECUTION),
            _family("F2", True, [False, False], FailureLayer.L3_EVENT),
            _family("F3", True, [True, False], FailureLayer.L3_EVENT),
            _family("F4", False, [False, False], FailureLayer.L4_WORKFLOW),
            _family("F5", False, [True, False], FailureLayer.L5_TOOLCHAIN),
        ]

    def test_family_type_distribution(self, sample_families):
        dist = family_type_distribution(sample_families)
        assert dist["stable-correct"] == 1
        assert dist["fragile"] == 2
        assert dist["unsolved"] == 1
        assert dist["inconsistent"] == 1

    def test_fragility_rate(self, sample_families):
        assert fragility_rate(sample_families) == pytest.approx(2 / 3)

    def test_fragility_rate_no_eligible(self):
        assert fragility_rate([_family("F1", False, [False])]) == 0.0

    def test_mean_severity(self, sample_families):
        assert mean_severity(sample_families) == pytest.approx(0.5)

    def test_layer_conditioned_fragility(self, sample_families):
        lcf = layer_conditioned_fragility(sample_families)
        assert lcf[FailureLayer.L2_EXECUTION.value] == 0.0
        assert lcf[FailureLayer.L3_EVENT.value] == 1.0

    def test_failure_layer_distribution(self, sample_families):
        dist = failure_layer_distribution(sample_families)
        assert dist[FailureLayer.L3_EVENT.value] == 2

    def test_cf_exposed_failure_count(self, sample_families):
        assert cf_exposed_failure_count(sample_families) == 1


class TestAnnotation:
    def test_samples_fragile_instances(self):
        from bcbench.analysis.annotation import sample_failures

        families = [
            _family("F1", True, [True, True]),
            _family("F2", True, [False, False], FailureLayer.L3_EVENT),
            _family("F3", False, [False], FailureLayer.L4_WORKFLOW),
        ]
        rows = sample_failures(families)
        assert len(rows) == 4
        assert rows[0]["family_type"] == "fragile"

    def test_max_samples_limit(self):
        from bcbench.analysis.annotation import sample_failures

        rows = sample_failures([_family("F1", True, [False, False, False])], max_samples=2)
        assert len(rows) == 2

    def test_writes_csv(self, tmp_path):
        from bcbench.analysis.annotation import sample_failures, write_annotation_csv

        rows = sample_failures([_family("F1", True, [False], FailureLayer.L2_EXECUTION)])
        write_annotation_csv(rows, tmp_path / "annotations.csv")
        assert (tmp_path / "annotations.csv").exists()
