from bcbench.results.bugfix import BugFixResult
from tests.conftest import create_dataset_entry, create_evaluation_context


class TestEvaluationResultFactories:
    def test_create_success_result_fills_all_fields_correctly(self, sample_evaluation_context):
        result = BugFixResult.create_success(sample_evaluation_context, "test_patch")

        assert result.instance_id == sample_evaluation_context.entry.instance_id
        assert result.project == "Shopify"
        assert result.resolved is True
        assert result.build is True
        assert result.model == "test-model"
        assert result.agent_name == "test-agent"
        assert result.error_message is None

    def test_create_build_failure_result_fills_all_fields_correctly(self, sample_evaluation_context):
        error_msg = "Build failed: src/app"
        result = BugFixResult.create_build_failure(sample_evaluation_context, "test_patch", error_msg)

        assert result.instance_id == sample_evaluation_context.entry.instance_id
        assert result.project == "Shopify"
        assert result.resolved is False
        assert result.build is False
        assert result.model == "test-model"
        assert result.agent_name == "test-agent"
        assert result.error_message == error_msg

    def test_create_test_failure_result_fills_all_fields_correctly(self, sample_evaluation_context):
        result = BugFixResult.create_test_failure(sample_evaluation_context, "test_patch")

        assert result.instance_id == sample_evaluation_context.entry.instance_id
        assert result.project == "Shopify"
        assert result.resolved is False
        assert result.build is True
        assert result.model == "test-model"
        assert result.agent_name == "test-agent"
        assert result.error_message == "Tests failed"

    def test_different_context_values_are_correctly_populated(self, tmp_path):
        entry = create_dataset_entry(
            instance_id="microsoftInternal__NAV-456",
            project_paths=["App\\Layers\\W1\\BaseApp", "App\\Layers\\W1\\BaseAppTest"],
        )
        context = create_evaluation_context(
            tmp_path,
            entry=entry,
            agent_name="different-agent",
            model="different-model",
        )

        result = BugFixResult.create_success(context, "test_patch")

        assert result.instance_id == "microsoftInternal__NAV-456"
        assert result.project == "BaseApp"
        assert result.model == "different-model"
        assert result.agent_name == "different-agent"

    def test_build_failure_with_patch_application_error_message(self, sample_evaluation_context):
        error_msg = "Failed to apply custom_fix.patch"
        result = BugFixResult.create_build_failure(sample_evaluation_context, "test_patch", error_msg)

        assert result.error_message == error_msg

    def test_build_failure_with_different_project_path(self, sample_evaluation_context):
        error_msg = "Build failed: src/components/module1"
        result = BugFixResult.create_build_failure(sample_evaluation_context, "test_patch", error_msg)

        assert result.error_message == error_msg
