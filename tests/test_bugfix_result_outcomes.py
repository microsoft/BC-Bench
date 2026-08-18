from itertools import product

import pytest

from bcbench.results.bugfix import BugFixResult, FixCheckOutcome, TestCheckOutcome


def passing_test_outcome() -> TestCheckOutcome:
    return TestCheckOutcome(build=True, pre_patch_failed=True, post_patch_passed=True)


def passing_fix_outcome() -> FixCheckOutcome:
    return FixCheckOutcome(build=True, passed=True)


class TestOutcomeCorrectness:
    def test_test_outcome_needs_all_three_flags(self):
        assert passing_test_outcome().correct is True
        assert TestCheckOutcome(build=True, pre_patch_failed=True).correct is False
        assert TestCheckOutcome(build=False, pre_patch_failed=True, post_patch_passed=True).correct is False

    def test_fix_outcome_needs_build_and_pass(self):
        assert passing_fix_outcome().correct is True
        assert FixCheckOutcome(build=True, passed=False).correct is False
        assert FixCheckOutcome(build=False, passed=True).correct is False


class TestFromOutcomes:
    @pytest.mark.parametrize(
        ("test_outcome", "fix_outcome", "expected_resolved"),
        [
            (passing_test_outcome(), passing_fix_outcome(), True),
            (TestCheckOutcome(build=True), passing_fix_outcome(), False),
            (passing_test_outcome(), FixCheckOutcome(build=True), False),
            (TestCheckOutcome(), FixCheckOutcome(), False),
        ],
    )
    def test_resolved_requires_both_halves(self, sample_evaluation_context, test_outcome, fix_outcome, expected_resolved):
        result = BugFixResult.from_outcomes(sample_evaluation_context, "patch", test_outcome, fix_outcome)

        assert result.resolved is expected_resolved

    def test_build_requires_both_halves_to_build(self, sample_evaluation_context):
        result = BugFixResult.from_outcomes(
            sample_evaluation_context,
            "patch",
            TestCheckOutcome(build=True, pre_patch_failed=True, post_patch_passed=True),
            FixCheckOutcome(build=False),
        )

        assert result.build is False
        assert result.test_build is True
        assert result.fix_build is False

    def test_sub_metrics_are_carried_over(self, sample_evaluation_context):
        result = BugFixResult.from_outcomes(
            sample_evaluation_context,
            "patch",
            TestCheckOutcome(build=True, pre_patch_failed=True, post_patch_passed=False),
            FixCheckOutcome(build=True, passed=True),
        )

        assert result.pre_patch_failed is True
        assert result.post_patch_passed is False
        assert result.fix_passed is True
        assert result.test_correct is False
        assert result.fix_correct is True

    def test_error_messages_from_both_stages_are_joined(self, sample_evaluation_context):
        result = BugFixResult.from_outcomes(
            sample_evaluation_context,
            "patch",
            TestCheckOutcome(error_message="test stage broke"),
            FixCheckOutcome(error_message="fix stage broke"),
        )

        assert "test stage broke" in result.error_message
        assert "fix stage broke" in result.error_message

    def test_no_error_message_when_both_stages_clean(self, sample_evaluation_context):
        result = BugFixResult.from_outcomes(sample_evaluation_context, "patch", passing_test_outcome(), passing_fix_outcome())

        assert result.error_message is None

    def test_category_metrics_expose_derived_keys_for_evaluators(self, sample_evaluation_context):
        result = BugFixResult.from_outcomes(sample_evaluation_context, "patch", passing_test_outcome(), passing_fix_outcome())

        assert result.category_metrics == {
            "resolved": True,
            "build": True,
            "test_build": True,
            "pre_patch_failed": True,
            "post_patch_passed": True,
            "fix_build": True,
            "fix_passed": True,
            "test_correct": True,
            "fix_correct": True,
        }

    def test_display_row_shows_both_halves(self, sample_evaluation_context):
        result = BugFixResult.from_outcomes(
            sample_evaluation_context,
            "patch",
            passing_test_outcome(),
            FixCheckOutcome(build=True, passed=False),
        )

        assert result.display_row == {"Test Correct": "Yes", "Fix Correct": "No"}


class TestCorrectnessFormulasStayInSync:
    # BugFixResult must re-derive correctness from persisted flat booleans alone, so these
    # formulas guard against silent drift from TestCheckOutcome/FixCheckOutcome.correct.

    @pytest.mark.parametrize(("build", "pre_patch_failed", "post_patch_passed"), list(product([False, True], repeat=3)))
    def test_test_correct_matches_test_outcome_correct(self, sample_evaluation_context, build, pre_patch_failed, post_patch_passed):
        test_outcome = TestCheckOutcome(build=build, pre_patch_failed=pre_patch_failed, post_patch_passed=post_patch_passed)
        fix_outcome = passing_fix_outcome()

        result = BugFixResult.from_outcomes(sample_evaluation_context, "patch", test_outcome, fix_outcome)

        assert result.test_correct == test_outcome.correct
        assert result.resolved == (test_outcome.correct and fix_outcome.correct)

    @pytest.mark.parametrize(("build", "passed"), list(product([False, True], repeat=2)))
    def test_fix_correct_matches_fix_outcome_correct(self, sample_evaluation_context, build, passed):
        test_outcome = passing_test_outcome()
        fix_outcome = FixCheckOutcome(build=build, passed=passed)

        result = BugFixResult.from_outcomes(sample_evaluation_context, "patch", test_outcome, fix_outcome)

        assert result.fix_correct == fix_outcome.correct
        assert result.resolved == (test_outcome.correct and fix_outcome.correct)
