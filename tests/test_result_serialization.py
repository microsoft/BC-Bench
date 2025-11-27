import json

import pytest

from bcbench.commands.result import _experiments_equal
from bcbench.results.base import create_result_from_json
from bcbench.results.evaluation_result import EvaluationResultSummary
from bcbench.types import AgentMetrics, EvaluationCategory, ExperimentConfiguration
from tests.conftest import create_bugfix_result, create_testgen_result


class TestCategorySerialization:
    @pytest.fixture
    def sample_result_bug_fix(self):
        return create_bugfix_result(
            instance_id="test__bug-fix-1",
            project="app",
            metrics=AgentMetrics(execution_time=100.0, prompt_tokens=1000, completion_tokens=500),
        )

    @pytest.fixture
    def sample_result_test_gen(self):
        return create_testgen_result(
            instance_id="test__test-gen-1",
            project="app",
            resolved=False,
            metrics=AgentMetrics(execution_time=150.0, prompt_tokens=2000, completion_tokens=800),
        )

    def test_bug_fix_category_saves_as_string(self, tmp_path, sample_result_bug_fix):
        output_file = tmp_path / "result.jsonl"
        sample_result_bug_fix.save(tmp_path, "result.jsonl")

        with open(output_file) as f:
            data = json.loads(f.readline())

        assert data["category"] == "bug-fix"
        assert isinstance(data["category"], str)

    def test_test_generation_category_saves_as_string(self, tmp_path, sample_result_test_gen):
        output_file = tmp_path / "result.jsonl"
        sample_result_test_gen.save(tmp_path, "result.jsonl")

        with open(output_file) as f:
            data = json.loads(f.readline())

        assert data["category"] == "test-generation"
        assert isinstance(data["category"], str)

    def test_bug_fix_category_loads_from_string(self):
        payload = {
            "instance_id": "test__instance",
            "project": "app",
            "model": "gpt-4o",
            "agent_name": "copilot-cli",
            "category": "bug-fix",
            "resolved": True,
            "build": True,
            "generated_patch": "patch",
        }

        result = create_result_from_json(payload)

        assert result.category == EvaluationCategory.BUG_FIX

    def test_test_generation_category_loads_from_string(self):
        payload = {
            "instance_id": "test__instance",
            "project": "app",
            "model": "gpt-4o",
            "agent_name": "copilot-cli",
            "category": "test-generation",
            "resolved": False,
            "build": True,
            "generated_patch": "test patch",
        }

        result = create_result_from_json(payload)

        assert result.category == EvaluationCategory.TEST_GENERATION

    def test_round_trip_bug_fix(self, tmp_path):
        original = create_bugfix_result(instance_id="round-trip-test", project="test-project", model="test-model", agent_name="test-agent")

        # Save to file
        original.save(tmp_path, "test.jsonl")

        # Load from file
        with open(tmp_path / "test.jsonl") as f:
            data = json.loads(f.readline())

        loaded = create_result_from_json(data)

        assert loaded.category == original.category
        assert loaded.category == EvaluationCategory.BUG_FIX

    def test_round_trip_test_generation(self, tmp_path):
        original = create_testgen_result(instance_id="round-trip-test-gen", project="test-project", model="test-model", agent_name="test-agent", resolved=False)

        # Save to file
        original.save(tmp_path, "test.jsonl")

        # Load from file
        with open(tmp_path / "test.jsonl") as f:
            data = json.loads(f.readline())

        loaded = create_result_from_json(data)

        assert loaded.category == original.category
        assert loaded.category == EvaluationCategory.TEST_GENERATION

    def test_summary_category_saves_as_string(self, sample_result_bug_fix, tmp_path):
        summary = EvaluationResultSummary.from_results([sample_result_bug_fix], "test_run")
        summary.save(tmp_path, "summary.json")

        with open(tmp_path / "summary.json") as f:
            data = json.load(f)

        assert data["category"] == "bug-fix"
        assert isinstance(data["category"], str)

    def test_summary_category_loads_from_string(self):
        payload = {
            "total": 10,
            "resolved": 8,
            "failed": 2,
            "build": 9,
            "date": "2025-11-18",
            "model": "gpt-4o",
            "category": "test-generation",
            "agent_name": "copilot-cli",
            "average_duration": 120.5,
            "average_prompt_tokens": 1500.0,
            "average_completion_tokens": 600.0,
        }

        summary = EvaluationResultSummary.model_validate(payload)

        # Pydantic handles the enum conversion automatically
        assert summary.category == EvaluationCategory.TEST_GENERATION

    def test_test_generation_pre_patch_failed_in_jsonl(self, tmp_path):
        result = create_testgen_result(
            instance_id="test__pre-patch",
            project="app",
            resolved=True,
            pre_patch_failed=True,
            post_patch_passed=True,
        )

        output_file = tmp_path / "result.jsonl"
        result.save(tmp_path, "result.jsonl")

        with open(output_file) as f:
            data = json.loads(f.readline())

        assert "pre_patch_failed" in data
        assert data["pre_patch_failed"] is True

    def test_no_experiment_saves_as_none(self, tmp_path, sample_result_bug_fix):
        output_file = tmp_path / "result.jsonl"
        sample_result_bug_fix.save(tmp_path, "result.jsonl")

        with open(output_file) as f:
            data = json.loads(f.readline())

        assert data["experiment"] is None

    def test_some_experiment_saves_as_dict(self, tmp_path, sample_result_bug_fix):
        sample_result_bug_fix.experiment = ExperimentConfiguration(custom_agent="custom-agent", custom_instructions=True)

        output_file = tmp_path / "result.jsonl"
        sample_result_bug_fix.save(tmp_path, "result.jsonl")

        with open(output_file) as f:
            data = json.loads(f.readline())

        assert data["experiment"] is not None
        assert isinstance(data["experiment"], dict)
        assert data["experiment"]["custom_agent"] == "custom-agent"
        assert data["experiment"]["custom_instructions"] is True
        assert data["experiment"]["mcp_servers"] is None


class TestExperimentsEqual:
    def test_both_none_are_equal(self):
        assert _experiments_equal(None, None) is True

    def test_none_and_empty_config_are_equal(self):
        empty = ExperimentConfiguration()
        assert _experiments_equal(None, empty) is True
        assert _experiments_equal(empty, None) is True

    def test_none_and_explicit_empty_config_are_equal(self):
        empty = ExperimentConfiguration(mcp_servers=None, custom_instructions=False, custom_agent=None)
        assert _experiments_equal(None, empty) is True
        assert _experiments_equal(empty, None) is True

    def test_two_empty_configs_are_equal(self):
        empty1 = ExperimentConfiguration()
        empty2 = ExperimentConfiguration(mcp_servers=None, custom_instructions=False, custom_agent=None)
        assert _experiments_equal(empty1, empty2) is True

    def test_non_empty_config_not_equal_to_none(self):
        config = ExperimentConfiguration(mcp_servers=["pylance"])
        assert _experiments_equal(None, config) is False
        assert _experiments_equal(config, None) is False

    def test_non_empty_config_not_equal_to_empty(self):
        config = ExperimentConfiguration(custom_instructions=True)
        empty = ExperimentConfiguration()
        assert _experiments_equal(config, empty) is False
        assert _experiments_equal(empty, config) is False

    def test_same_non_empty_configs_are_equal(self):
        config1 = ExperimentConfiguration(mcp_servers=["pylance"], custom_instructions=True)
        config2 = ExperimentConfiguration(mcp_servers=["pylance"], custom_instructions=True)
        assert _experiments_equal(config1, config2) is True

    def test_different_non_empty_configs_are_not_equal(self):
        config1 = ExperimentConfiguration(mcp_servers=["pylance"])
        config2 = ExperimentConfiguration(mcp_servers=["filesystem"])
        assert _experiments_equal(config1, config2) is False

    def test_config_with_custom_agent_not_equal_to_none(self):
        config = ExperimentConfiguration(custom_agent="my-agent")
        assert _experiments_equal(None, config) is False
        assert _experiments_equal(config, None) is False
