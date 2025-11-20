import json

import pytest

from bcbench.dataset import DatasetEntry
from bcbench.results.bugfix import BugFixResult
from bcbench.results.result_writer import write_bceval_results
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import EvaluationCategory


class TestWriteBcevalResults:
    @pytest.fixture
    def sample_dataset_entry(self):
        return DatasetEntry(
            instance_id="test__instance-1",
            repo="test/repo",
            base_commit="a" * 40,
            environment_setup_version="26.0",
            fail_to_pass=[{"codeunitID": 100, "functionName": ["TestFunction"]}],
            pass_to_pass=[],
            project_paths=["src/app"],
            patch="diff --git a/test.al b/test.al\n--- a/test.al\n+++ b/test.al\n@@ -1 +1 @@\n-old\n+new",
        )

    @pytest.fixture
    def sample_dataset_file(self, tmp_path, sample_dataset_entry):
        dataset_path = tmp_path / "dataset.jsonl"
        with open(dataset_path, "w") as f:
            entry_dict = {
                "instance_id": sample_dataset_entry.instance_id,
                "repo": sample_dataset_entry.repo,
                "base_commit": sample_dataset_entry.base_commit,
                "environment_setup_version": sample_dataset_entry.environment_setup_version,
                "fail_to_pass": sample_dataset_entry.fail_to_pass,
                "pass_to_pass": sample_dataset_entry.pass_to_pass,
                "project_paths": sample_dataset_entry.project_paths,
                "patch": sample_dataset_entry.patch,
            }
            f.write(json.dumps(entry_dict) + "\n")
        return dataset_path

    @pytest.fixture
    def result_with_all_fields(self):
        return BugFixResult(
            instance_id="test__instance-1",
            project="app",
            model="gpt-4o",
            agent_name="copilot-cli",
            category=EvaluationCategory.BUG_FIX,
            resolved=True,
            build=True,
            generated_patch="diff --git a/test.al b/test.al\n--- a/test.al\n+++ b/test.al\n@@ -1 +1 @@\n-old\n+new",
            error_message=None,
            agent_execution_time=120.5,
            prompt_tokens=5000,
            completion_tokens=1200,
        )

    @pytest.fixture
    def result_with_none_metrics(self):
        return TestGenerationResult(
            instance_id="test__instance-1",
            project="app",
            model="gpt-4o",
            agent_name="copilot-cli",
            category=EvaluationCategory.TEST_GENERATION,
            resolved=False,
            build=False,
            generated_patch="",
            error_message="Failed to build",
            agent_execution_time=None,
            prompt_tokens=None,
            completion_tokens=None,
        )

    def test_writes_bceval_results_with_all_fields(self, tmp_path, sample_dataset_file, result_with_all_fields):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        write_bceval_results(
            results=[result_with_all_fields],
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

        assert data["id"] == "test__instance-1"
        assert data["metadata"]["model"] == "gpt-4o"
        assert data["metadata"]["prompt_tokens"] == 5000
        assert data["metadata"]["completion_tokens"] == 1200
        assert data["metadata"]["latency"] == 120.5
        assert data["metadata"]["resolved"] is True
        assert data["metadata"]["run_id"] == "test_run_123"
        assert data["metadata"]["project"] == "app"

    def test_handles_none_prompt_tokens(self, tmp_path, sample_dataset_file, result_with_none_metrics):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        write_bceval_results(
            results=[result_with_none_metrics],
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

    def test_handles_mixed_results(self, tmp_path, sample_dataset_file, result_with_all_fields, result_with_none_metrics):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        write_bceval_results(
            results=[result_with_all_fields, result_with_none_metrics],
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

    def test_includes_expected_fields_in_bceval_format(self, tmp_path, sample_dataset_file, result_with_all_fields):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        write_bceval_results(
            results=[result_with_all_fields],
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

        non_matching_result = BugFixResult(
            instance_id="test__nonexistent",
            project="app",
            model="gpt-4o",
            agent_name="copilot-cli",
            category=EvaluationCategory.BUG_FIX,
            resolved=False,
            build=False,
            prompt_tokens=1000,
            completion_tokens=200,
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

    def test_handles_partial_none_metrics(self, tmp_path, sample_dataset_file):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = BugFixResult(
            instance_id="test__instance-1",
            project="app",
            model="gpt-4o",
            agent_name="copilot-cli",
            category=EvaluationCategory.BUG_FIX,
            resolved=True,
            build=True,
            agent_execution_time=100.0,
            prompt_tokens=None,  # Only prompt_tokens is None
            completion_tokens=1500,
        )

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
