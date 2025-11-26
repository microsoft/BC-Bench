import json
from datetime import date

import pytest

from bcbench.results.evaluation_result import EvaluationResultSummary
from bcbench.types import AgentMetrics, EvaluationCategory
from tests.conftest import create_bugfix_result, create_testgen_result


class TestEvaluationResultSummary:
    def test_summary_save_creates_json_file(self, tmp_path):
        summary = EvaluationResultSummary(
            total=10,
            resolved=8,
            failed=2,
            build=9,
            date=date(2025, 1, 15),
            model="gpt-4o",
            category=EvaluationCategory.BUG_FIX,
            agent_name="copilot-cli",
            average_duration=120.5,
            average_prompt_tokens=5000.0,
            average_completion_tokens=1200.0,
        )

        summary_file = "test.json"
        summary.save(tmp_path, summary_file)

        output_file = tmp_path / summary_file
        assert output_file.exists()

        with open(output_file) as f:
            data = json.load(f)

        assert data["total"] == 10
        assert data["resolved"] == 8
        assert data["failed"] == 2
        assert data["build"] == 9
        assert data["date"] == "2025-01-15"
        assert data["model"] == "gpt-4o"
        assert data["agent_name"] == "copilot-cli"
        assert data["average_duration"] == 120.5
        assert data["average_prompt_tokens"] == 5000.0
        assert data["average_completion_tokens"] == 1200.0

    def test_summary_save_with_custom_filename(self, tmp_path):
        summary = EvaluationResultSummary(
            total=5,
            resolved=4,
            failed=1,
            build=5,
            date=date(2025, 1, 20),
            model="gpt-4",
            category=EvaluationCategory.TEST_GENERATION,
            agent_name="mini-bc-agent",
            average_duration=90.0,
            average_prompt_tokens=3000.0,
            average_completion_tokens=800.0,
        )

        summary.save(tmp_path, summary_file="custom_summary.json")

        output_file = tmp_path / "custom_summary.json"
        assert output_file.exists()


class TestFromResults:
    @pytest.fixture
    def sample_results(self):
        return [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
            create_bugfix_result(
                instance_id="test__2",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=150.0, prompt_tokens=6000, completion_tokens=1500),
            ),
            create_bugfix_result(
                instance_id="test__3",
                project="app",
                resolved=False,
                build=False,
                error_message="Build failed",
                metrics=AgentMetrics(execution_time=80.0, prompt_tokens=4000, completion_tokens=800),
            ),
        ]

    def test_from_results_creates_correct_summary(self, sample_results):
        summary = EvaluationResultSummary.from_results(sample_results, run_id="test_run_123")

        assert summary.total == 3
        assert summary.resolved == 2
        assert summary.failed == 1
        assert summary.build == 2
        assert summary.model == "gpt-4o"
        assert summary.agent_name == "copilot-cli"
        assert summary.github_run_id == "test_run_123"
        assert summary.date == date.today()

    def test_from_results_calculates_averages_correctly(self, sample_results):
        summary = EvaluationResultSummary.from_results(sample_results, run_id="test_run_123")

        # Average duration: (100 + 150 + 80) / 3 = 110
        assert summary.average_duration == pytest.approx(110.0)
        # Average prompt tokens: (5000 + 6000 + 4000) / 3 = 5000
        assert summary.average_prompt_tokens == pytest.approx(5000.0)
        # Average completion tokens: (1000 + 1500 + 800) / 3 = 1100
        assert summary.average_completion_tokens == pytest.approx(1100.0)

    def test_from_results_handles_none_values_in_metrics(self):
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
            create_bugfix_result(
                instance_id="test__2",
                project="app",
                resolved=False,
                build=False,
                error_message="Error",
                metrics=None,
            ),
        ]

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        # Should only average non-None values
        assert summary.average_duration == pytest.approx(100.0)
        assert summary.average_prompt_tokens == pytest.approx(5000.0)
        assert summary.average_completion_tokens == pytest.approx(1000.0)

    def test_from_results_with_all_none_metrics_returns_zero(self):
        results = [
            create_testgen_result(
                instance_id="test__1",
                project="app",
                resolved=False,
                build=False,
                error_message="Error",
                metrics=None,
            ),
        ]

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        assert summary.average_duration == 0.0
        assert summary.average_prompt_tokens == 0.0
        assert summary.average_completion_tokens == 0.0
