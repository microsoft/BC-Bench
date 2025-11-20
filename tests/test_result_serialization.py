import json

import pytest

from bcbench.results.base import create_result_from_json
from bcbench.results.bugfix import BugFixResult
from bcbench.results.evaluation_result import EvaluationResultSummary
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import EvaluationCategory


class TestCategorySerialization:
    @pytest.fixture
    def sample_result_bug_fix(self):
        return BugFixResult(
            instance_id="test__bug-fix-1",
            project="app",
            model="gpt-4o",
            agent_name="copilot-cli",
            category=EvaluationCategory.BUG_FIX,
            resolved=True,
            build=True,
            generated_patch="patch content",
            agent_execution_time=100.0,
            prompt_tokens=1000,
            completion_tokens=500,
        )

    @pytest.fixture
    def sample_result_test_gen(self):
        return TestGenerationResult(
            instance_id="test__test-gen-1",
            project="app",
            model="gpt-4o",
            agent_name="copilot-cli",
            category=EvaluationCategory.TEST_GENERATION,
            resolved=False,
            build=True,
            generated_patch="test patch content",
            agent_execution_time=150.0,
            prompt_tokens=2000,
            completion_tokens=800,
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
        original = BugFixResult(
            instance_id="round-trip-test",
            project="test-project",
            model="test-model",
            agent_name="test-agent",
            category=EvaluationCategory.BUG_FIX,
            resolved=True,
            build=True,
        )

        # Save to file
        original.save(tmp_path, "test.jsonl")

        # Load from file
        with open(tmp_path / "test.jsonl") as f:
            data = json.loads(f.readline())

        loaded = create_result_from_json(data)

        assert loaded.category == original.category
        assert loaded.category == EvaluationCategory.BUG_FIX

    def test_round_trip_test_generation(self, tmp_path):
        original = TestGenerationResult(
            instance_id="round-trip-test-gen",
            project="test-project",
            model="test-model",
            agent_name="test-agent",
            category=EvaluationCategory.TEST_GENERATION,
            resolved=False,
            build=True,
        )

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

        summary = EvaluationResultSummary.from_json(payload)

        # Note: from_json receives string and assigns directly to category
        # The current implementation stores it as the enum's value string
        assert summary.category == "test-generation"

    def test_test_generation_pre_patch_failed_in_jsonl(self, tmp_path):
        result = TestGenerationResult(
            instance_id="test__pre-patch",
            project="app",
            model="gpt-4o",
            agent_name="copilot-cli",
            category=EvaluationCategory.TEST_GENERATION,
            resolved=True,
            build=True,
            generated_patch="test content",
            pre_patch_failed=True,
            post_patch_passed=True,
        )

        output_file = tmp_path / "result.jsonl"
        result.save(tmp_path, "result.jsonl")

        with open(output_file) as f:
            data = json.loads(f.readline())

        assert "pre_patch_failed" in data
        assert data["pre_patch_failed"] is True
