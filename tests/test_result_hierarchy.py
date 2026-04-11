"""Tests for the result and summary class hierarchies after the category refactor.

Covers:
- BaseEvaluationResult vs ExecutionBasedEvaluationResult field separation
- status_label, category_metrics, display_row polymorphism
- from_json dispatch to correct subclass
- EvaluationResultSummary.from_results dispatch and super() chain
- ExecutionBasedEvaluationResultSummary category-specific aggregation
- display_summary on summaries
- display.py console/GitHub summary rendering
"""

from datetime import date

import pytest

from bcbench.results.base import BaseEvaluationResult, ExecutionBasedEvaluationResult
from bcbench.results.bugfix import BugFixResult
from bcbench.results.display import create_console_summary, create_github_job_summary
from bcbench.results.summary import (
    EvaluationResultSummary,
    ExecutionBasedEvaluationResultSummary,
)
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import AgentMetrics, EvaluationCategory
from tests.conftest import create_bugfix_result, create_evaluation_context, create_testgen_result


def _make_config_with_summary(summary_path: str):
    """Create a config mock with github_step_summary set."""
    from bcbench.config import get_config

    config = get_config()
    # Return a shallow copy-like object that overrides env.github_step_summary
    from unittest.mock import MagicMock

    mock = MagicMock(wraps=config)
    mock.env.github_step_summary = summary_path
    return mock


# ---------------------------------------------------------------------------
# BaseEvaluationResult
# ---------------------------------------------------------------------------


class TestBaseEvaluationResult:
    def test_base_has_no_resolved_or_build(self):
        assert "resolved" not in BaseEvaluationResult.model_fields
        assert "build" not in BaseEvaluationResult.model_fields

    def test_execution_based_has_resolved_and_build(self):
        assert "resolved" in ExecutionBasedEvaluationResult.model_fields
        assert "build" in ExecutionBasedEvaluationResult.model_fields

    def test_bugfix_inherits_execution_based(self):
        assert issubclass(BugFixResult, ExecutionBasedEvaluationResult)

    def test_testgen_inherits_execution_based(self):
        assert issubclass(TestGenerationResult, ExecutionBasedEvaluationResult)


# ---------------------------------------------------------------------------
# status_label
# ---------------------------------------------------------------------------


class TestStatusLabel:
    def test_base_completed(self):
        result = create_bugfix_result(resolved=True)
        assert result.status_label == "Success"

    def test_base_timeout(self):
        result = create_bugfix_result(resolved=False, build=False)
        result.timeout = True
        assert result.status_label == "Timeout"

    def test_execution_based_success(self):
        result = create_bugfix_result(resolved=True, build=True)
        assert result.status_label == "Success"

    def test_execution_based_failed(self):
        result = create_bugfix_result(resolved=False, build=True, error_message="Tests failed")
        assert result.status_label == "Failed"


# ---------------------------------------------------------------------------
# category_metrics
# ---------------------------------------------------------------------------


class TestCategoryMetrics:
    def test_bugfix_category_metrics(self):
        result = create_bugfix_result(resolved=True, build=True)
        assert result.category_metrics == {"resolved": True, "build": True}

    def test_bugfix_failed_category_metrics(self):
        result = create_bugfix_result(resolved=False, build=False)
        assert result.category_metrics == {"resolved": False, "build": False}

    def test_testgen_category_metrics_includes_extra_fields(self):
        result = create_testgen_result(resolved=True, build=True, pre_patch_failed=True, post_patch_passed=True)
        metrics = result.category_metrics
        assert metrics["resolved"] is True
        assert metrics["build"] is True
        assert metrics["pre_patch_failed"] is True
        assert metrics["post_patch_passed"] is True

    def test_testgen_category_metrics_defaults(self):
        result = create_testgen_result()
        metrics = result.category_metrics
        assert metrics["pre_patch_failed"] is False
        assert metrics["post_patch_passed"] is False


# ---------------------------------------------------------------------------
# display_row
# ---------------------------------------------------------------------------


class TestDisplayRow:
    def test_bugfix_display_row_is_empty(self):
        result = create_bugfix_result()
        assert result.display_row == {}

    def test_testgen_display_row_has_columns(self):
        result = create_testgen_result(pre_patch_failed=True, post_patch_passed=False)
        row = result.display_row
        assert row["Pre-Patch Failed"] == "Yes"
        assert row["Post-Patch Passed"] == "No"

    def test_testgen_display_row_no_flags(self):
        result = create_testgen_result(pre_patch_failed=False, post_patch_passed=False)
        row = result.display_row
        assert row["Pre-Patch Failed"] == "No"
        assert row["Post-Patch Passed"] == "No"


# ---------------------------------------------------------------------------
# from_json dispatch
# ---------------------------------------------------------------------------


class TestFromJsonDispatch:
    def test_from_json_returns_bugfix_result(self):
        payload = create_bugfix_result().model_dump(mode="json")
        loaded = BaseEvaluationResult.from_json(payload)
        assert isinstance(loaded, BugFixResult)

    def test_from_json_returns_testgen_result(self):
        payload = create_testgen_result(pre_patch_failed=True).model_dump(mode="json")
        loaded = BaseEvaluationResult.from_json(payload)
        assert isinstance(loaded, TestGenerationResult)
        assert loaded.pre_patch_failed is True

    def test_from_json_preserves_all_fields(self):
        original = create_bugfix_result(
            instance_id="test__round-trip",
            resolved=True,
            build=True,
            output="patch content",
            error_message=None,
        )
        loaded = BaseEvaluationResult.from_json(original.model_dump(mode="json"))
        assert loaded.instance_id == original.instance_id
        assert loaded.output == original.output

    def test_from_json_unknown_category_raises(self):
        payload = create_bugfix_result().model_dump(mode="json")
        payload["category"] = "nonexistent"
        with pytest.raises(ValueError, match="nonexistent"):
            BaseEvaluationResult.from_json(payload)


# ---------------------------------------------------------------------------
# create_agent_timeout_failure
# ---------------------------------------------------------------------------


class TestCreateAgentTimeout:
    def test_timeout_sets_fields(self, tmp_path):
        ctx = create_evaluation_context(tmp_path)
        result = BugFixResult.create_agent_timeout_failure(ctx)
        assert result.timeout is True
        assert result.error_message == "Agent timed out"
        assert result.status_label == "Timeout"


# ---------------------------------------------------------------------------
# EvaluationResultSummary.from_results — dispatch + super() chain
# ---------------------------------------------------------------------------


class TestSummaryFromResults:
    def test_base_dispatches_to_execution_based_for_bugfix(self):
        results = [create_bugfix_result(instance_id="test__1", resolved=True)]
        summary = EvaluationResultSummary.from_results(results, run_id="run1")
        assert isinstance(summary, ExecutionBasedEvaluationResultSummary)

    def test_base_dispatches_to_execution_based_for_testgen(self):
        results = [create_testgen_result(instance_id="test__1")]
        summary = EvaluationResultSummary.from_results(results, run_id="run1")
        assert isinstance(summary, ExecutionBasedEvaluationResultSummary)

    def test_subclass_direct_call_also_works(self):
        results = [create_bugfix_result(instance_id="test__1", resolved=True)]
        summary = ExecutionBasedEvaluationResultSummary.from_results(results, run_id="run1")
        assert isinstance(summary, ExecutionBasedEvaluationResultSummary)
        assert summary.resolved == 1

    def test_common_fields_computed(self):
        results = [
            create_bugfix_result(
                instance_id="test__1",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=1000, completion_tokens=500),
            ),
            create_bugfix_result(
                instance_id="test__2",
                resolved=False,
                metrics=AgentMetrics(execution_time=200.0, prompt_tokens=3000, completion_tokens=1500),
            ),
        ]
        summary = EvaluationResultSummary.from_results(results, run_id="run1")

        assert summary.total == 2
        assert summary.model == "gpt-4o"
        assert summary.agent_name == "copilot-cli"
        assert summary.average_duration == pytest.approx(150.0)
        assert summary.average_prompt_tokens == pytest.approx(2000.0)
        assert summary.average_completion_tokens == pytest.approx(1000.0)
        assert summary.date == date.today()

    def test_category_specific_fields_computed(self):
        results = [
            create_bugfix_result(instance_id="test__1", resolved=True, build=True),
            create_bugfix_result(instance_id="test__2", resolved=False, build=True),
            create_bugfix_result(instance_id="test__3", resolved=False, build=False),
        ]
        summary = EvaluationResultSummary.from_results(results, run_id="run1")

        assert isinstance(summary, ExecutionBasedEvaluationResultSummary)
        assert summary.resolved == 1
        assert summary.failed == 2
        assert summary.build == 2
        assert summary.percentage == pytest.approx(33.3)

    def test_instance_results_populated(self):
        results = [
            create_bugfix_result(instance_id="test__a", resolved=True),
            create_bugfix_result(instance_id="test__b", resolved=False),
        ]
        summary = EvaluationResultSummary.from_results(results, run_id="run1")

        assert isinstance(summary, ExecutionBasedEvaluationResultSummary)
        assert summary.instance_results == {"test__a": True, "test__b": False}


# ---------------------------------------------------------------------------
# display_summary
# ---------------------------------------------------------------------------


class TestDisplaySummary:
    def test_execution_based_display_summary(self):
        summary = ExecutionBasedEvaluationResultSummary(
            total=10,
            resolved=7,
            failed=3,
            build=9,
            percentage=70.0,
            date=date.today(),
            model="gpt-4o",
            agent_name="copilot",
            category=EvaluationCategory.BUG_FIX,
            average_duration=100.0,
            average_prompt_tokens=1000.0,
            average_completion_tokens=500.0,
            benchmark_version="0.1.0",
        )
        display = summary.display_summary()
        assert display == {"resolved": 7, "failed": 3, "build": 9, "percentage": 70.0}


# ---------------------------------------------------------------------------
# Summary from_json dispatch
# ---------------------------------------------------------------------------


class TestSummaryFromJson:
    def test_from_json_returns_execution_based_for_bugfix(self):
        payload = {
            "total": 5,
            "resolved": 3,
            "failed": 2,
            "build": 4,
            "percentage": 60.0,
            "date": "2025-01-15",
            "model": "gpt-4o",
            "category": "bug-fix",
            "agent_name": "copilot",
            "average_duration": 100.0,
            "average_prompt_tokens": 1000.0,
            "average_completion_tokens": 500.0,
            "benchmark_version": "0.1.0",
        }
        summary = EvaluationResultSummary.from_json(payload)
        assert isinstance(summary, ExecutionBasedEvaluationResultSummary)
        assert summary.resolved == 3

    def test_from_json_unknown_category_raises(self):
        payload = {
            "total": 5,
            "date": "2025-01-15",
            "model": "gpt-4o",
            "category": "nonexistent",
            "agent_name": "copilot",
            "average_duration": 100.0,
            "average_prompt_tokens": 1000.0,
            "average_completion_tokens": 500.0,
            "benchmark_version": "0.1.0",
        }
        with pytest.raises(ValueError, match="nonexistent"):
            EvaluationResultSummary.from_json(payload)


# ---------------------------------------------------------------------------
# display.py — console and GitHub summary
# ---------------------------------------------------------------------------


class TestConsoleSummary:
    def test_console_summary_renders(self, capsys):
        results = [
            create_bugfix_result(instance_id="test__1", resolved=True),
            create_bugfix_result(instance_id="test__2", resolved=False, error_message="Build failed"),
        ]
        create_console_summary(results, EvaluationResultSummary.from_results(results, run_id=""))
        captured = capsys.readouterr()
        assert "test__1" in captured.out
        assert "test__2" in captured.out
        assert "Evaluation Results Summary" in captured.out

    def test_console_summary_shows_testgen_data_values(self, capsys):
        results = [
            create_testgen_result(instance_id="test__1", resolved=True, pre_patch_failed=True, post_patch_passed=True),
        ]
        create_console_summary(results, EvaluationResultSummary.from_results(results, run_id=""))
        captured = capsys.readouterr()
        # Rich truncates column headers, but data values "Yes" should appear
        assert "Yes" in captured.out
        assert "test__1" in captured.out


class TestGitHubJobSummary:
    def test_github_summary_renders_markdown(self, tmp_path, monkeypatch):
        summary_file = tmp_path / "summary.md"
        monkeypatch.setattr("bcbench.results.display.get_config", lambda: _make_config_with_summary(str(summary_file)))
        results = [
            create_bugfix_result(instance_id="test__1", resolved=True),
            create_bugfix_result(instance_id="test__2", resolved=False, error_message="Build failed"),
        ]
        create_github_job_summary(results, EvaluationResultSummary.from_results(results, run_id=""))
        content = summary_file.read_text()
        assert "test__1" in content
        assert "test__2" in content
        assert "bug-fix" in content

    def test_github_summary_includes_testgen_columns(self, tmp_path, monkeypatch):
        summary_file = tmp_path / "summary.md"
        monkeypatch.setattr("bcbench.results.display.get_config", lambda: _make_config_with_summary(str(summary_file)))
        results = [
            create_testgen_result(instance_id="test__1", resolved=True, pre_patch_failed=True, post_patch_passed=True),
        ]
        create_github_job_summary(results, EvaluationResultSummary.from_results(results, run_id=""))
        content = summary_file.read_text()
        assert "Pre-Patch Failed" in content
        assert "Post-Patch Passed" in content

    def test_github_summary_includes_tool_usage(self, tmp_path, monkeypatch):
        summary_file = tmp_path / "summary.md"
        monkeypatch.setattr("bcbench.results.display.get_config", lambda: _make_config_with_summary(str(summary_file)))
        results = [
            create_bugfix_result(
                instance_id="test__1",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, tool_usage={"bash": 5, "view": 3}),
            ),
        ]
        create_github_job_summary(results, EvaluationResultSummary.from_results(results, run_id=""))
        content = summary_file.read_text()
        assert "Tool Usage" in content
        assert "bash" in content
