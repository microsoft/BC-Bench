import json
from datetime import date

import pytest

from bcbench.results.evaluation_result import EvaluationResultSummary
from bcbench.types import AgentMetrics, EvaluationCategory, ExperimentConfiguration
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


class TestExperimentConfiguration:
    def test_is_empty_with_all_defaults(self):
        experiment = ExperimentConfiguration()
        assert experiment.is_empty() is True

    def test_is_empty_with_explicit_defaults(self):
        experiment = ExperimentConfiguration(mcp_servers=None, custom_instructions=False, custom_agent=None)
        assert experiment.is_empty() is True

    def test_is_empty_with_mcp_servers(self):
        experiment = ExperimentConfiguration(mcp_servers=["pylance"])
        assert experiment.is_empty() is False

    def test_is_empty_with_custom_instructions(self):
        experiment = ExperimentConfiguration(custom_instructions=True)
        assert experiment.is_empty() is False

    def test_is_empty_with_custom_agent(self):
        experiment = ExperimentConfiguration(custom_agent="my-agent")
        assert experiment.is_empty() is False

    def test_summary_with_experiment_configuration(self):
        experiment = ExperimentConfiguration(
            mcp_servers=["pylance", "filesystem"],
            custom_instructions=True,
            custom_agent="custom-bc-agent",
        )
        summary = EvaluationResultSummary(
            total=5,
            resolved=3,
            failed=2,
            build=4,
            date=date(2025, 1, 15),
            model="gpt-4o",
            category=EvaluationCategory.BUG_FIX,
            agent_name="copilot-cli",
            average_duration=100.0,
            average_prompt_tokens=4000.0,
            average_completion_tokens=1000.0,
            experiment=experiment,
        )

        assert summary.experiment is not None
        assert summary.experiment.mcp_servers == ["pylance", "filesystem"]
        assert summary.experiment.custom_instructions is True
        assert summary.experiment.custom_agent == "custom-bc-agent"

    def test_summary_without_experiment_configuration(self):
        summary = EvaluationResultSummary(
            total=5,
            resolved=3,
            failed=2,
            build=4,
            date=date(2025, 1, 15),
            model="gpt-4o",
            category=EvaluationCategory.BUG_FIX,
            agent_name="copilot-cli",
            average_duration=100.0,
            average_prompt_tokens=4000.0,
            average_completion_tokens=1000.0,
        )

        assert summary.experiment is None

    def test_summary_save_includes_experiment_in_json(self, tmp_path):
        experiment = ExperimentConfiguration(
            mcp_servers=["pylance"],
            custom_instructions=True,
        )
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
            experiment=experiment,
        )

        summary.save(tmp_path, "summary_with_experiment.json")

        with open(tmp_path / "summary_with_experiment.json") as f:
            data = json.load(f)

        assert "experiment" in data
        assert data["experiment"]["mcp_servers"] == ["pylance"]
        assert data["experiment"]["custom_instructions"] is True
        assert data["experiment"]["custom_agent"] is None

    def test_summary_save_with_none_experiment(self, tmp_path):
        summary = EvaluationResultSummary(
            total=5,
            resolved=3,
            failed=2,
            build=4,
            date=date(2025, 1, 15),
            model="gpt-4o",
            category=EvaluationCategory.BUG_FIX,
            agent_name="copilot-cli",
            average_duration=100.0,
            average_prompt_tokens=4000.0,
            average_completion_tokens=1000.0,
            experiment=None,
        )

        summary.save(tmp_path, "summary_no_experiment.json")

        with open(tmp_path / "summary_no_experiment.json") as f:
            data = json.load(f)

        assert data["experiment"] is None

    def test_from_results_extracts_experiment_from_first_result(self):
        experiment = ExperimentConfiguration(
            mcp_servers=["pylance", "filesystem"],
            custom_instructions=True,
            custom_agent="custom-bc-agent",
        )
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
                metrics=AgentMetrics(execution_time=150.0, prompt_tokens=6000, completion_tokens=1500),
            ),
        ]
        # Set experiment on the first result
        results[0].experiment = experiment

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        assert summary.experiment is not None
        assert summary.experiment.mcp_servers == ["pylance", "filesystem"]
        assert summary.experiment.custom_instructions is True
        assert summary.experiment.custom_agent == "custom-bc-agent"

    def test_from_results_with_no_experiment_returns_none(self):
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
        ]

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        assert summary.experiment is None

    def test_from_results_normalizes_empty_experiment_to_none(self):
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
        ]
        # Set an empty experiment config (all defaults)
        results[0].experiment = ExperimentConfiguration()

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        # Should be normalized to None
        assert summary.experiment is None

    def test_from_results_normalizes_explicit_empty_experiment_to_none(self):
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
        ]
        # Set an explicitly empty experiment config
        results[0].experiment = ExperimentConfiguration(mcp_servers=None, custom_instructions=False, custom_agent=None)

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        # Should be normalized to None
        assert summary.experiment is None

    def test_from_results_preserves_non_empty_experiment(self):
        experiment = ExperimentConfiguration(mcp_servers=["pylance"], custom_instructions=True)
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
        ]
        results[0].experiment = experiment

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        # Should preserve non-empty experiment
        assert summary.experiment is not None
        assert summary.experiment.mcp_servers == ["pylance"]
        assert summary.experiment.custom_instructions is True
