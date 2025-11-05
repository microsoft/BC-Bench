import json
from datetime import date

import pytest

from bcbench.evaluate.evaluation_result import EvaluationResultSummary, summarize_results


class TestEvaluationResultSummary:
    def test_summary_save_creates_json_file(self, tmp_path):
        summary = EvaluationResultSummary(
            total=10,
            resolved=8,
            failed=2,
            build=9,
            date=date(2025, 1, 15),
            model="gpt-4o",
            agent_name="copilot-cli",
            average_duration=120.5,
            average_prompt_tokens=5000.0,
            average_completion_tokens=1200.0,
        )

        summary.save(tmp_path)

        output_file = tmp_path / "evaluation_summary.json"
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
            agent_name="mini-bc-agent",
            average_duration=90.0,
            average_prompt_tokens=3000.0,
            average_completion_tokens=800.0,
        )

        summary.save(tmp_path, summary_file="custom_summary.json")

        output_file = tmp_path / "custom_summary.json"
        assert output_file.exists()


class TestSummarizeResults:
    @pytest.fixture
    def results_dir(self, tmp_path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        return results_dir

    @pytest.fixture
    def sample_results_file(self, results_dir):
        results_file = results_dir / "instance_results.jsonl"
        results = [
            {
                "instance_id": "test__1",
                "resolved": True,
                "build": True,
                "model": "gpt-4o",
                "agent_name": "copilot-cli",
                "error_message": None,
                "environment_setup_version": "25.1",
                "agent_execution_time": 100.0,
                "prompt_tokens": 5000,
                "completion_tokens": 1000,
            },
            {
                "instance_id": "test__2",
                "resolved": True,
                "build": True,
                "model": "gpt-4o",
                "agent_name": "copilot-cli",
                "error_message": None,
                "environment_setup_version": "25.1",
                "agent_execution_time": 150.0,
                "prompt_tokens": 6000,
                "completion_tokens": 1500,
            },
            {
                "instance_id": "test__3",
                "resolved": False,
                "build": False,
                "model": "gpt-4o",
                "agent_name": "copilot-cli",
                "error_message": "Build failed",
                "environment_setup_version": "25.1",
                "agent_execution_time": 80.0,
                "prompt_tokens": 4000,
                "completion_tokens": 800,
            },
        ]

        with open(results_file, "w") as f:
            for result in results:
                f.write(json.dumps(result) + "\n")

        return results_file

    def test_summarize_creates_summary_file(self, results_dir, sample_results_file):
        assert sample_results_file.exists()

        summarize_results(results_dir, "*.jsonl", "test_run_123")

        summary_file = results_dir / "evaluation_summary.json"
        assert summary_file.exists()

        with open(summary_file) as f:
            summary = json.load(f)

        assert summary["total"] == 3
        assert summary["resolved"] == 2
        assert summary["failed"] == 1
        assert summary["build"] == 2
        assert summary["model"] == "gpt-4o"
        assert summary["agent_name"] == "copilot-cli"
        assert summary["github_run_id"] == "test_run_123"

    def test_summarize_calculates_averages_correctly(self, results_dir, sample_results_file):
        assert sample_results_file.exists()

        summarize_results(results_dir, "*.jsonl", "test_run_123")

        summary_file = results_dir / "evaluation_summary.json"
        with open(summary_file) as f:
            summary = json.load(f)

        # Average duration: (100 + 150 + 80) / 3 = 110
        assert summary["average_duration"] == pytest.approx(110.0)
        # Average prompt tokens: (5000 + 6000 + 4000) / 3 = 5000
        assert summary["average_prompt_tokens"] == pytest.approx(5000.0)
        # Average completion tokens: (1000 + 1500 + 800) / 3 = 1100
        assert summary["average_completion_tokens"] == pytest.approx(1100.0)

    def test_summarize_handles_none_values_in_metrics(self, results_dir):
        results_file = results_dir / "instance_results.jsonl"
        results = [
            {
                "instance_id": "test__1",
                "resolved": True,
                "build": True,
                "model": "gpt-4o",
                "agent_name": "copilot-cli",
                "error_message": None,
                "environment_setup_version": "25.1",
                "agent_execution_time": 100.0,
                "prompt_tokens": 5000,
                "completion_tokens": 1000,
            },
            {
                "instance_id": "test__2",
                "resolved": False,
                "build": False,
                "model": "gpt-4o",
                "agent_name": "copilot-cli",
                "error_message": "Error",
                "environment_setup_version": "25.1",
                "agent_execution_time": None,
                "prompt_tokens": None,
                "completion_tokens": None,
            },
        ]

        with open(results_file, "w") as f:
            for result in results:
                f.write(json.dumps(result) + "\n")

        summarize_results(results_dir, "*.jsonl", "test_run_123")

        summary_file = results_dir / "evaluation_summary.json"
        with open(summary_file) as f:
            summary = json.load(f)

        # Should only average non-None values
        assert summary["average_duration"] == pytest.approx(100.0)
        assert summary["average_prompt_tokens"] == pytest.approx(5000.0)
        assert summary["average_completion_tokens"] == pytest.approx(1000.0)

    def test_summarize_with_all_none_metrics_returns_zero(self, results_dir):
        results_file = results_dir / "instance_results.jsonl"
        results = [
            {
                "instance_id": "test__1",
                "resolved": False,
                "build": False,
                "model": "gpt-4o",
                "agent_name": "copilot-cli",
                "error_message": "Error",
                "environment_setup_version": "25.1",
                "agent_execution_time": None,
                "prompt_tokens": None,
                "completion_tokens": None,
            },
        ]

        with open(results_file, "w") as f:
            for result in results:
                f.write(json.dumps(result) + "\n")

        summarize_results(results_dir, "*.jsonl", "test_run_123")

        summary_file = results_dir / "evaluation_summary.json"
        with open(summary_file) as f:
            summary = json.load(f)

        assert summary["average_duration"] == 0.0
        assert summary["average_prompt_tokens"] == 0.0
        assert summary["average_completion_tokens"] == 0.0

    def test_summarize_raises_error_when_no_results_found(self, results_dir):
        with pytest.raises(RuntimeError, match="No results files matching"):
            summarize_results(results_dir, "*.jsonl", "test_run_123")

    def test_summarize_raises_error_when_result_files_empty(self, results_dir):
        # Create empty file
        results_file = results_dir / "instance_results.jsonl"
        results_file.touch()

        with pytest.raises(RuntimeError, match="No results found in the result files"):
            summarize_results(results_dir, "*.jsonl", "test_run_123")
