from bcbench.config import get_config
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.bugfix import BugFixResult
from bcbench.results.codereview import CodeReviewResultSummary
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate, LeaderboardAggregate
from bcbench.results.summary import EvaluationResultSummary
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import AgentHarness, EvaluationCategory
from tests.conftest import create_codereview_result, create_dataset_entry, create_evaluation_context


class TestEvaluationResultFactories:
    def test_create_success_result_fills_all_fields_correctly(self, sample_evaluation_context):
        result = BugFixResult.create_success(sample_evaluation_context, "test_patch")

        assert result.instance_id == sample_evaluation_context.entry.instance_id
        assert result.project == "Shopify"
        assert result.resolved is True
        assert result.build is True
        assert result.model == "test-model"
        assert result.agent_name == AgentHarness.COPILOT
        assert result.error_message is None

    def test_create_build_failure_result_fills_all_fields_correctly(self, sample_evaluation_context):
        error_msg = "Build failed: src/app"
        result = BugFixResult.create_build_failure(sample_evaluation_context, "test_patch", error_msg)

        assert result.instance_id == sample_evaluation_context.entry.instance_id
        assert result.project == "Shopify"
        assert result.resolved is False
        assert result.build is False
        assert result.model == "test-model"
        assert result.agent_name == AgentHarness.COPILOT
        assert result.error_message == error_msg

    def test_create_test_failure_result_fills_all_fields_correctly(self, sample_evaluation_context):
        result = BugFixResult.create_test_failure(sample_evaluation_context, "test_patch")

        assert result.instance_id == sample_evaluation_context.entry.instance_id
        assert result.project == "Shopify"
        assert result.resolved is False
        assert result.build is True
        assert result.model == "test-model"
        assert result.agent_name == AgentHarness.COPILOT
        assert result.error_message == "Tests failed"

    def test_different_context_values_are_correctly_populated(self, tmp_path):
        entry = create_dataset_entry(
            instance_id="microsoftInternal__NAV-456",
            project_paths=["App\\Layers\\W1\\BaseApp", "App\\Layers\\W1\\BaseAppTest"],
        )
        context = create_evaluation_context(
            tmp_path,
            entry=entry,
            agent_name=AgentHarness.CLAUDE,
            model="different-model",
        )

        result = BugFixResult.create_success(context, "test_patch")

        assert result.instance_id == "microsoftInternal__NAV-456"
        assert result.project == "BaseApp"
        assert result.model == "different-model"
        assert result.agent_name == AgentHarness.CLAUDE

    def test_build_failure_with_patch_application_error_message(self, sample_evaluation_context):
        error_msg = "Failed to apply custom_fix.patch"
        result = BugFixResult.create_build_failure(sample_evaluation_context, "test_patch", error_msg)

        assert result.error_message == error_msg

    def test_build_failure_with_different_project_path(self, sample_evaluation_context):
        error_msg = "Build failed: src/components/module1"
        result = BugFixResult.create_build_failure(sample_evaluation_context, "test_patch", error_msg)

        assert result.error_message == error_msg

    def test_test_generation_pre_patch_failure_sets_category_state(self, sample_evaluation_context):
        result = TestGenerationResult.create_pre_patch_failure(sample_evaluation_context, "test_patch", "Passed pre-patch")

        assert result.resolved is False
        assert result.build is True
        assert result.pre_patch_failed is False
        assert result.post_patch_passed is False
        assert result.error_message == "Passed pre-patch"

    def test_test_generation_post_patch_failure_sets_category_state(self, sample_evaluation_context):
        result = TestGenerationResult.create_post_patch_failure(sample_evaluation_context, "test_patch", "Failed post-patch")

        assert result.resolved is False
        assert result.build is True
        assert result.pre_patch_failed is True
        assert result.post_patch_passed is False
        assert result.error_message == "Failed post-patch"

    def test_judge_models_are_populated_from_shared_config(self, tmp_path):
        config = get_config().judge
        context = create_evaluation_context(tmp_path, category=EvaluationCategory.NL2AL)

        lm_checklist_result = JudgeBasedEvaluationResult.create_raw(context, "output")
        code_review_result = create_codereview_result()
        summary = EvaluationResultSummary.from_results([code_review_result], "run")
        aggregate = LeaderboardAggregate.from_runs([summary])
        assert isinstance(summary, CodeReviewResultSummary)
        assert isinstance(aggregate, CodeReviewLeaderboardAggregate)

        assert lm_checklist_result.judge_model == config.lm_checklist_model
        assert code_review_result.judge_model == config.code_review_model
        assert summary.judge_model == code_review_result.judge_model
        assert aggregate.judge_model == code_review_result.judge_model
