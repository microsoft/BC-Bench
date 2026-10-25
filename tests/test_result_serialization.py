import json

import pytest

from bcbench.results.base import BaseEvaluationResult
from bcbench.results.summary import EvaluationResultSummary
from bcbench.types import (
    AgentHarness,
    AgentMetrics,
    BCalCompilationEvent,
    BCalExecutionFacts,
    BCalExecutionIdentity,
    BCalPackageProvenance,
    BCalPackageSource,
    BCalScenarioFailure,
    EvaluationCategory,
    ExperimentConfiguration,
    PRReviewMetrics,
)
from tests.conftest import create_bugfix_result, create_codereview_result, create_testgen_result


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

        with output_file.open() as f:
            data = json.loads(f.readline())

        assert data["category"] == "bug-fix"
        assert isinstance(data["category"], str)

    def test_test_generation_category_saves_as_string(self, tmp_path, sample_result_test_gen):
        output_file = tmp_path / "result.jsonl"
        sample_result_test_gen.save(tmp_path, "result.jsonl")

        with output_file.open() as f:
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
            "output": "patch",
        }

        result = BaseEvaluationResult.from_json(payload)

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
            "output": "test patch",
        }

        result = BaseEvaluationResult.from_json(payload)

        assert result.category == EvaluationCategory.TEST_GENERATION

    @pytest.mark.parametrize(
        "payload",
        [
            {"id": "nl2al__case", "output": "diff", "context": {"contractVersion": "1.0"}, "metadata": {}},
            {"Id": "nl2al__case", "Output": "diff", "Context": {"contractVersion": "1.0"}, "Metadata": {}},
        ],
    )
    def test_published_bceval_row_is_rejected_as_raw_result(self, payload):
        with pytest.raises(ValueError, match="Published bc-eval rows are not raw BC-Bench result JSONL"):
            BaseEvaluationResult.from_json(payload)

    def test_round_trip_bug_fix(self, tmp_path):
        original = create_bugfix_result(instance_id="round-trip-test", project="test-project", model="test-model", agent_name="test-agent")

        # Save to file
        original.save(tmp_path, "test.jsonl")

        # Load from file
        with (tmp_path / "test.jsonl").open() as f:
            data = json.loads(f.readline())

        loaded = BaseEvaluationResult.from_json(data)

        assert loaded.category == original.category
        assert loaded.category == EvaluationCategory.BUG_FIX

    def test_round_trip_test_generation(self, tmp_path):
        original = create_testgen_result(instance_id="round-trip-test-gen", project="test-project", model="test-model", agent_name="test-agent", resolved=False)

        # Save to file
        original.save(tmp_path, "test.jsonl")

        # Load from file
        with (tmp_path / "test.jsonl").open() as f:
            data = json.loads(f.readline())

        loaded = BaseEvaluationResult.from_json(data)

        assert loaded.category == original.category
        assert loaded.category == EvaluationCategory.TEST_GENERATION

    def test_summary_category_saves_as_string(self, sample_result_bug_fix, tmp_path):
        summary = EvaluationResultSummary.from_results([sample_result_bug_fix], "test_run")
        summary.save(tmp_path, "summary.json")

        with (tmp_path / "summary.json").open() as f:
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
            "benchmark_version": "0.1.0",
        }

        from bcbench.results.summary import EvaluationResultSummary

        summary = EvaluationResultSummary.from_json(payload)

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

        with output_file.open() as f:
            data = json.loads(f.readline())

        assert "pre_patch_failed" in data
        assert data["pre_patch_failed"] is True

    def test_no_experiment_saves_as_none(self, tmp_path, sample_result_bug_fix):
        output_file = tmp_path / "result.jsonl"
        sample_result_bug_fix.save(tmp_path, "result.jsonl")

        with output_file.open() as f:
            data = json.loads(f.readline())

        assert data["experiment"] is None

    def test_some_experiment_saves_as_dict(self, tmp_path, sample_result_bug_fix):
        sample_result_bug_fix.experiment = ExperimentConfiguration(custom_agent="custom-agent", custom_instructions=True)

        output_file = tmp_path / "result.jsonl"
        sample_result_bug_fix.save(tmp_path, "result.jsonl")

        with output_file.open() as f:
            data = json.loads(f.readline())

        assert data["experiment"] is not None
        assert isinstance(data["experiment"], dict)
        assert data["experiment"]["custom_agent"] == "custom-agent"
        assert data["experiment"]["custom_instructions"] is True
        assert data["experiment"]["mcp_servers"] is None

    def test_bcal_package_provenance_round_trips(self, tmp_path, sample_result_bug_fix):
        sample_result_bug_fix.bcal_package = BCalPackageProvenance(source=BCalPackageSource.EXPERIMENT, branch="private/user/change")
        sample_result_bug_fix.save(tmp_path, "result.jsonl")

        payload = json.loads((tmp_path / "result.jsonl").read_text(encoding="utf-8"))
        loaded = BaseEvaluationResult.from_json(payload)

        assert payload["bcal_package"] == {"source": "experiment", "branch": "private/user/change"}
        assert loaded.bcal_package == sample_result_bug_fix.bcal_package

    def test_bcal_evidence_and_execution_identity_round_trip(self, tmp_path, sample_result_bug_fix):
        identity = BCalExecutionIdentity(
            productVersion="1.2.3",
            sourceCommitSha="050e84b25a0890d532a52433a3256c4183e81c7e",
            buildConfiguration="Release",
            scenarioContractVersion="1.0",
            evidenceContractVersion="1.0",
        )
        evidence = {
            "contractVersion": "1.0",
            "executionIdentity": identity.model_dump(mode="json", by_alias=True),
            "trace": {"events": []},
        }
        sample_result_bug_fix.execution_identity = identity
        sample_result_bug_fix.evidence = evidence
        sample_result_bug_fix.save(tmp_path, "result.jsonl")

        payload = json.loads((tmp_path / "result.jsonl").read_text(encoding="utf-8"))
        loaded = BaseEvaluationResult.from_json(payload)

        assert loaded.execution_identity == identity
        assert loaded.evidence == evidence

    def test_bcal_failure_round_trip(self, tmp_path, sample_result_bug_fix):
        failure = BCalScenarioFailure(
            code="incomplete_execution",
            message="repair_budget_exhausted",
            stepId="benchmark-prompt",
            retryable=False,
        )
        sample_result_bug_fix.bcal_failure = failure
        sample_result_bug_fix.output = "diff --git a/src/Generated.al b/src/Generated.al\n+pageextension"
        sample_result_bug_fix.error_message = "BCal scenario exited with status 1"
        sample_result_bug_fix.save(tmp_path, "result.jsonl")

        payload = json.loads((tmp_path / "result.jsonl").read_text(encoding="utf-8"))
        loaded = BaseEvaluationResult.from_json(payload)

        assert payload["bcal_failure"] == {
            "code": "incomplete_execution",
            "message": "repair_budget_exhausted",
            "step_id": "benchmark-prompt",
            "retryable": False,
        }
        assert loaded.bcal_failure == failure
        assert loaded.output == sample_result_bug_fix.output
        assert loaded.error_message == sample_result_bug_fix.error_message

    def test_cohort_and_repetition_metadata_round_trip(self, tmp_path, sample_result_bug_fix):
        sample_result_bug_fix.cohort_name = "55-chat-completion-policy"
        sample_result_bug_fix.cohort_sha256 = "a" * 64
        sample_result_bug_fix.repetition_index = 2
        sample_result_bug_fix.repetition_count = 3

        sample_result_bug_fix.save(tmp_path, "result.jsonl")

        payload = json.loads((tmp_path / "result.jsonl").read_text(encoding="utf-8"))
        loaded = BaseEvaluationResult.from_json(payload)

        assert loaded.cohort_name == "55-chat-completion-policy"
        assert loaded.cohort_sha256 == "a" * 64
        assert loaded.repetition_index == 2
        assert loaded.repetition_count == 3

    def test_bcal_execution_facts_round_trip(self, tmp_path, sample_result_bug_fix):
        identity = BCalExecutionIdentity(
            productVersion="1.2.3",
            sourceCommitSha="050e84b25a0890d532a52433a3256c4183e81c7e",
            buildConfiguration="Release",
            scenarioContractVersion="1.0",
            evidenceContractVersion="1.0",
        )
        facts = BCalExecutionFacts(
            execution_identity=identity,
            scenario_completed=True,
            scenario_step_status="succeeded",
            step_compile_succeeded=True,
            compile_succeeded=True,
            compile_evidence_source="scenario_step",
            compilation_events=(
                BCalCompilationEvent(
                    sequence=33,
                    type="compilation_outcome",
                    scenarioStepId="benchmark-prompt",
                    iteration=6,
                    callId="call-compile",
                    operation="compile",
                    status="succeeded",
                    succeeded=True,
                ),
            ),
            evidence_status="present",
            trace_truncated=False,
        )
        sample_result_bug_fix.execution_facts = facts
        sample_result_bug_fix.save(tmp_path, "result.jsonl")

        payload = json.loads((tmp_path / "result.jsonl").read_text(encoding="utf-8"))
        loaded = BaseEvaluationResult.from_json(payload)

        assert loaded.execution_facts == facts

    def test_completion_review_model_round_trip(self, tmp_path, sample_result_bug_fix):
        sample_result_bug_fix.completion_review_model = "gpt-56-reasoning-sol"
        sample_result_bug_fix.save(tmp_path, "result.jsonl")

        payload = json.loads((tmp_path / "result.jsonl").read_text(encoding="utf-8"))
        loaded = BaseEvaluationResult.from_json(payload)

        assert loaded.completion_review_model == "gpt-56-reasoning-sol"

    @pytest.mark.parametrize(
        ("changes", "match"),
        [
            ({"cohort_name": "focus"}, "cohort_name and cohort_sha256"),
            ({"repetition_index": 1}, "repetition_index and repetition_count"),
            ({"repetition_index": 3, "repetition_count": 2}, "between 1 and repetition_count"),
            ({"cohort_name": "focus", "cohort_sha256": "a" * 64}, "cohort results must record repetition"),
        ],
    )
    def test_invalid_cohort_metadata_is_rejected(self, sample_result_bug_fix, changes, match):
        payload = sample_result_bug_fix.model_dump(mode="json")
        payload.update(changes)

        with pytest.raises(ValueError, match=match):
            BaseEvaluationResult.from_json(payload)

    def test_tool_usage_saves_as_dict(self, tmp_path):
        tool_usage = {"bash": 5, "view": 3, "search": 2}
        result = create_bugfix_result(
            instance_id="test__tool-usage",
            project="app",
            metrics=AgentMetrics(execution_time=100.0, tool_usage=tool_usage),
        )

        output_file = tmp_path / "result.jsonl"
        result.save(tmp_path, "result.jsonl")

        with output_file.open() as f:
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
            "output": "patch",
            "metrics": {
                "kind": "generic",
                "execution_time": 100.0,
                "prompt_tokens": 5000,
                "completion_tokens": 1000,
                "tool_usage": {"bash": 5, "view": 3},
            },
        }

        result = BaseEvaluationResult.from_json(payload)

        assert result.metrics is not None
        assert result.metrics.tool_usage is not None
        assert result.metrics.tool_usage["bash"] == 5
        assert result.metrics.tool_usage["view"] == 3

    def test_pr_review_metrics_round_trip(self, tmp_path):
        original = create_codereview_result(
            agent_name=AgentHarness.PR_REVIEW,
            metrics=PRReviewMetrics(
                execution_time=10.0,
                api_calls=2,
                usage_complete=True,
                copilot_cli_version="1.0.82",
            ),
        )
        original.save(tmp_path, "result.jsonl")

        payload = json.loads((tmp_path / "result.jsonl").read_text(encoding="utf-8"))
        loaded = BaseEvaluationResult.from_json(payload)

        assert payload["metrics"]["kind"] == "pr-review"
        assert isinstance(loaded.metrics, PRReviewMetrics)
        assert loaded.metrics.api_calls == 2
        assert loaded.metrics.copilot_cli_version == "1.0.82"

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
        with (tmp_path / "test.jsonl").open() as f:
            data = json.loads(f.readline())

        loaded = BaseEvaluationResult.from_json(data)

        assert loaded.metrics is not None
        assert loaded.metrics.tool_usage is not None
        assert original.metrics is not None
        assert original.metrics.tool_usage is not None
        assert loaded.metrics.tool_usage == original.metrics.tool_usage

    def test_model_dump_json_serializes_category_as_string_value(self):
        bug_fix = create_bugfix_result()
        test_gen = create_testgen_result()

        bug_fix_dump = bug_fix.model_dump(mode="json")
        test_gen_dump = test_gen.model_dump(mode="json")

        assert bug_fix_dump["category"] == "bug-fix"
        assert test_gen_dump["category"] == "test-generation"
        assert isinstance(bug_fix_dump["category"], str)
        assert isinstance(test_gen_dump["category"], str)
