import pytest

from bcbench.dataset import DatasetEntry
from bcbench.evaluate.evaluation_context import EvaluationContext
from bcbench.results import EvaluationResult


class TestEvaluationResultFactories:
    @pytest.fixture
    def sample_context(self, tmp_path) -> EvaluationContext:
        entry = DatasetEntry(
            instance_id="test__repo-123",
            repo="test/repo",
            base_commit="a" * 40,
            environment_setup_version="25.1",
            fail_to_pass=[{"codeunitID": 100, "functionName": ["Test1"]}],
            pass_to_pass=[],
            project_paths=["App\\Apps\\W1\\Shopify\\app"],
        )
        return EvaluationContext(
            entry=entry,
            repo_path=tmp_path / "repo",
            result_dir=tmp_path / "results",
            container_name="test-container",
            password="test-password",
            username="test-user",
            agent_name="test-agent",
            model="test-model",
        )

    def test_create_success_result_fills_all_fields_correctly(self, sample_context):
        result = EvaluationResult.create_success(sample_context, "test_patch")

        assert result.instance_id == "test__repo-123"
        assert result.project == "Shopify"
        assert result.resolved is True
        assert result.build is True
        assert result.model == "test-model"
        assert result.agent_name == "test-agent"
        assert result.error_message is None

    def test_create_build_failure_result_fills_all_fields_correctly(self, sample_context):
        error_msg = "Build failed: src/app"
        result = EvaluationResult.create_build_failure(sample_context, error_msg)

        assert result.instance_id == "test__repo-123"
        assert result.project == "Shopify"
        assert result.resolved is False
        assert result.build is False
        assert result.model == "test-model"
        assert result.agent_name == "test-agent"
        assert result.error_message == error_msg

    def test_create_test_failure_result_fills_all_fields_correctly(self, sample_context):
        result = EvaluationResult.create_test_failure(sample_context)

        assert result.instance_id == "test__repo-123"
        assert result.project == "Shopify"
        assert result.resolved is False
        assert result.build is True
        assert result.model == "test-model"
        assert result.agent_name == "test-agent"
        assert result.error_message == "Tests failed"

    def test_create_unexpected_error_result_fills_all_fields_correctly(self, sample_context):
        error = RuntimeError("something went wrong")
        result = EvaluationResult.create_unexpected_error(sample_context, error)

        assert result.instance_id == "test__repo-123"
        assert result.project == "Shopify"
        assert result.resolved is False
        assert result.build is False
        assert result.model == "test-model"
        assert result.agent_name == "test-agent"
        assert result.error_message == "Unexpected error: something went wrong"

    def test_different_context_values_are_correctly_populated(self, tmp_path):
        entry = DatasetEntry(
            instance_id="different__entry-456",
            repo="different/repo",
            base_commit="b" * 40,
            environment_setup_version="26.2",
            fail_to_pass=[{"codeunitID": 200, "functionName": ["Test2"]}],
            pass_to_pass=[],
            project_paths=["App\\Layers\\W1\\BaseApp"],
        )
        context = EvaluationContext(
            entry=entry,
            repo_path=tmp_path / "repo",
            result_dir=tmp_path / "results",
            container_name="different-container",
            password="different-password",
            username="different-user",
            agent_name="different-agent",
            model="different-model",
        )

        result = EvaluationResult.create_success(context, "test_patch")

        assert result.instance_id == "different__entry-456"
        assert result.project == "BaseApp"
        assert result.model == "different-model"
        assert result.agent_name == "different-agent"

    def test_build_failure_with_patch_application_error_message(self, sample_context):
        error_msg = "Failed to apply custom_fix.patch"
        result = EvaluationResult.create_build_failure(sample_context, error_msg)

        assert result.error_message == error_msg

    def test_build_failure_with_different_project_path(self, sample_context):
        error_msg = "Build failed: src/components/module1"
        result = EvaluationResult.create_build_failure(sample_context, error_msg)

        assert result.error_message == error_msg

    def test_unexpected_error_with_different_exception_types(self, sample_context):
        value_error = ValueError("invalid value")
        result = EvaluationResult.create_unexpected_error(sample_context, value_error)
        assert result.error_message is not None
        assert "invalid value" in result.error_message

        key_error = KeyError("missing_key")
        result = EvaluationResult.create_unexpected_error(sample_context, key_error)
        assert result.error_message is not None
        assert "missing_key" in result.error_message
