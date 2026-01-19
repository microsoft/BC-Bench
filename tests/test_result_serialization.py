import json

import pytest

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
            "percentage": 80.0,
            "date": "2025-11-18",
            "model": "gpt-4o",
            "category": "test-generation",
            "agent_name": "copilot-cli",
            "average_duration": 120.5,
            "average_prompt_tokens": 1500.0,
            "average_completion_tokens": 600.0,
            "average_llm_duration": 80.0,
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

    def test_tool_usage_saves_as_dict(self, tmp_path):
        tool_usage = {"bash": 5, "view": 3, "search": 2}
        result = create_bugfix_result(
            instance_id="test__tool-usage",
            project="app",
            metrics=AgentMetrics(execution_time=100.0, tool_usage=tool_usage),
        )

        output_file = tmp_path / "result.jsonl"
        result.save(tmp_path, "result.jsonl")

        with open(output_file) as f:
            data = json.loads(f.readline())

        assert data["metrics"]["tool_usage"] is not None
        assert isinstance(data["metrics"]["tool_usage"], dict)
        assert data["metrics"]["tool_usage"] == {"bash": 5, "view": 3, "search": 2}

    def test_tool_usage_loads_from_json(self):
        payload = {
            "instance_id": "test__instance",
            "project": "app",
            "model": "gpt-4o",
            "agent_name": "copilot-cli",
            "category": "bug-fix",
            "resolved": True,
            "build": True,
            "generated_patch": "patch",
            "metrics": {
                "execution_time": 100.0,
                "prompt_tokens": 5000,
                "completion_tokens": 1000,
                "tool_usage": {"bash": 5, "view": 3},
            },
        }

        result = create_result_from_json(payload)

        assert result.metrics is not None
        assert result.metrics.tool_usage is not None
        assert result.metrics.tool_usage["bash"] == 5
        assert result.metrics.tool_usage["view"] == 3

    def test_tool_usage_round_trip(self, tmp_path):
        tool_usage = {"bash": 10, "view": 5}
        original = create_bugfix_result(
            instance_id="round-trip-tool-usage",
            project="test-project",
            model="test-model",
            agent_name="test-agent",
            metrics=AgentMetrics(execution_time=120.0, tool_usage=tool_usage),
        )

        # Save to file
        original.save(tmp_path, "test.jsonl")

        # Load from file
        with open(tmp_path / "test.jsonl") as f:
            data = json.loads(f.readline())

        loaded = create_result_from_json(data)

        assert loaded.metrics is not None
        assert loaded.metrics.tool_usage is not None
        assert original.metrics is not None
        assert original.metrics.tool_usage is not None
        assert loaded.metrics.tool_usage == original.metrics.tool_usage
