import json
from unittest.mock import patch

from bcbench.dataset import DatasetEntry
from bcbench.results.result_writer import write_bceval_results
from bcbench.types import AgentMetrics
from tests.conftest import VALID_INSTANCE_ID, create_bugfix_result


class TestWriteBcevalResults:
    def test_writes_bceval_results_with_all_fields(self, tmp_path, sample_dataset_file, sample_bugfix_result_with_metrics, problem_statement_dir):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch.object(DatasetEntry, "problem_statement_dir", property(lambda self: problem_statement_dir)):
            write_bceval_results(
                results=[sample_bugfix_result_with_metrics],
                out_dir=output_dir,
                run_id="test_run_123",
                dataset_path=sample_dataset_file,
                output_filename="results.jsonl",
            )

        output_file = output_dir / "results.jsonl"
        assert output_file.exists()

        with open(output_file) as f:
            line = f.readline()
            data = json.loads(line)

        assert data["id"] == VALID_INSTANCE_ID
        assert data["metadata"]["model"] == "gpt-4o"
        assert data["metadata"]["prompt_tokens"] == 5000
        assert data["metadata"]["completion_tokens"] == 1200
        assert data["metadata"]["latency"] == 120.5
        assert data["metadata"]["resolved"] is True
        assert data["metadata"]["run_id"] == "test_run_123"
        assert data["metadata"]["project"] == "Shopify"

    def test_handles_none_prompt_tokens(self, tmp_path, sample_dataset_file, sample_testgen_result, problem_statement_dir):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch.object(DatasetEntry, "problem_statement_dir", property(lambda self: problem_statement_dir)):
            write_bceval_results(
                results=[sample_testgen_result],
                out_dir=output_dir,
                run_id="test_run_456",
                dataset_path=sample_dataset_file,
                output_filename="results.jsonl",
            )

        output_file = output_dir / "results.jsonl"
        with open(output_file) as f:
            line = f.readline()
            data = json.loads(line)

        assert data["metadata"]["prompt_tokens"] == 0
        assert data["metadata"]["completion_tokens"] == 0
        assert data["metadata"]["latency"] == 0

    def test_handles_mixed_results(self, tmp_path, sample_dataset_file, sample_bugfix_result_with_metrics, sample_testgen_result, problem_statement_dir):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch.object(DatasetEntry, "problem_statement_dir", property(lambda self: problem_statement_dir)):
            write_bceval_results(
                results=[sample_bugfix_result_with_metrics, sample_testgen_result],
                out_dir=output_dir,
                run_id="test_run_789",
                dataset_path=sample_dataset_file,
                output_filename="results.jsonl",
            )

        output_file = output_dir / "results.jsonl"
        with open(output_file) as f:
            lines = f.readlines()

        assert len(lines) == 2

        data1 = json.loads(lines[0])
        assert data1["metadata"]["prompt_tokens"] == 5000
        assert data1["metadata"]["completion_tokens"] == 1200
        assert data1["metadata"]["latency"] == 120.5

        data2 = json.loads(lines[1])
        assert data2["metadata"]["prompt_tokens"] == 0
        assert data2["metadata"]["completion_tokens"] == 0
        assert data2["metadata"]["latency"] == 0

    def test_includes_expected_fields_in_bceval_format(self, tmp_path, sample_dataset_file, sample_bugfix_result_with_metrics, problem_statement_dir):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch.object(DatasetEntry, "problem_statement_dir", property(lambda self: problem_statement_dir)):
            write_bceval_results(
                results=[sample_bugfix_result_with_metrics],
                out_dir=output_dir,
                run_id="test_run_abc",
                dataset_path=sample_dataset_file,
                output_filename="results.jsonl",
            )

        output_file = output_dir / "results.jsonl"
        with open(output_file) as f:
            data = json.loads(f.readline())

        # Check all required bceval fields are present
        assert "id" in data
        assert "input" in data
        assert "expected" in data
        assert "output" in data
        assert "context" in data
        assert "metadata" in data
        assert "tags" in data

    def test_skips_results_without_matching_dataset_entry(self, tmp_path, sample_dataset_file):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        non_matching_result = create_bugfix_result(
            instance_id="microsoftInternal__NAV-999999",
            resolved=False,
            build=False,
            metrics=AgentMetrics(prompt_tokens=1000, completion_tokens=200),
        )

        write_bceval_results(
            results=[non_matching_result],
            out_dir=output_dir,
            run_id="test_run_xyz",
            dataset_path=sample_dataset_file,
            output_filename="results.jsonl",
        )

        output_file = output_dir / "results.jsonl"
        with open(output_file) as f:
            lines = f.readlines()

        # Should have 0 lines since no matching dataset entry
        assert len(lines) == 0

    def test_handles_partial_none_metrics(self, tmp_path, sample_dataset_file, problem_statement_dir):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = create_bugfix_result(metrics=AgentMetrics(execution_time=100.0, prompt_tokens=None, completion_tokens=1500))

        with patch.object(DatasetEntry, "problem_statement_dir", property(lambda self: problem_statement_dir)):
            write_bceval_results(
                results=[result],
                out_dir=output_dir,
                run_id="test_run_partial",
                dataset_path=sample_dataset_file,
                output_filename="results.jsonl",
            )

        output_file = output_dir / "results.jsonl"
        with open(output_file) as f:
            data = json.loads(f.readline())

        assert data["metadata"]["prompt_tokens"] == 0
        assert data["metadata"]["completion_tokens"] == 1500
        assert data["metadata"]["latency"] == 100.0
