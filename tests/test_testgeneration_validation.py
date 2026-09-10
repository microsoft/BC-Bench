import subprocess
from unittest.mock import patch

import pytest
import yaml

from bcbench.config import get_config
from bcbench.dataset import TestEntry
from bcbench.evaluate.testgeneration import TestGenerationPipeline, _get_test_generation_input_mode
from bcbench.exceptions import TestExecutionError, TestInfrastructureError
from bcbench.operations import bc_operations
from bcbench.operations.test_execution import TestExpectation, TestRunSummary
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import EvaluationCategory
from tests.conftest import create_evaluation_context


def test_get_test_generation_input_mode_valid_gold_patch():
    config_content = yaml.dump({"prompt": {"test-generation-input": "gold-patch"}})

    with patch("pathlib.Path.read_text", return_value=config_content):
        result = _get_test_generation_input_mode()

    assert result == "gold-patch"


def test_get_test_generation_input_mode_valid_problem_statement():
    config_content = yaml.dump({"prompt": {"test-generation-input": "problem-statement"}})

    with patch("pathlib.Path.read_text", return_value=config_content):
        result = _get_test_generation_input_mode()

    assert result == "problem-statement"


def test_get_test_generation_input_mode_valid_both():
    config_content = yaml.dump({"prompt": {"test-generation-input": "both"}})

    with patch("pathlib.Path.read_text", return_value=config_content):
        result = _get_test_generation_input_mode()

    assert result == "both"


def test_get_test_generation_input_mode_defaults_to_problem_statement():
    config_content = yaml.dump({"prompt": {}})

    with patch("pathlib.Path.read_text", return_value=config_content):
        result = _get_test_generation_input_mode()

    assert result == "problem-statement"


def test_get_test_generation_input_mode_invalid_with_underscore():
    config_content = yaml.dump({"prompt": {"test-generation-input": "gold_patch"}})

    with patch("pathlib.Path.read_text", return_value=config_content), pytest.raises(ValueError, match="Invalid test-generation-input mode: 'gold_patch'") as exc_info:
        _get_test_generation_input_mode()

    assert "gold-patch" in str(exc_info.value)
    assert "Use hyphens, not underscores" in str(exc_info.value)


def test_get_test_generation_input_mode_invalid_random_value():
    config_content = yaml.dump({"prompt": {"test-generation-input": "invalid-mode"}})

    with patch("pathlib.Path.read_text", return_value=config_content), pytest.raises(ValueError, match="Invalid test-generation-input mode: 'invalid-mode'") as exc_info:
        _get_test_generation_input_mode()

    assert "gold-patch" in str(exc_info.value)
    assert "problem-statement" in str(exc_info.value)
    assert "both" in str(exc_info.value)


def test_get_test_generation_input_mode_empty_string():
    config_content = yaml.dump({"prompt": {"test-generation-input": ""}})

    with patch("pathlib.Path.read_text", return_value=config_content), pytest.raises(ValueError, match="Invalid test-generation-input mode: ''"):
        _get_test_generation_input_mode()


def test_test_generation_any_fail_error_is_classified_as_pre_patch(tmp_path, monkeypatch):
    context = create_evaluation_context(tmp_path, category=EvaluationCategory.TEST_GENERATION)
    generated_tests = [TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))]
    calls: list[tuple[object, ...]] = []

    monkeypatch.setattr("bcbench.evaluate.testgeneration.categorize_projects", lambda _paths: (["test"], ["app"]))
    monkeypatch.setattr("bcbench.evaluate.testgeneration.clean_project_paths", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.stage_and_get_diff", lambda _repo_path: "generated patch")
    monkeypatch.setattr("bcbench.evaluate.testgeneration.extract_file_paths_from_patch", lambda _patch: [])
    monkeypatch.setattr("bcbench.evaluate.testgeneration.extract_tests_from_patch", lambda *_args: generated_tests)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.build_and_publish_projects", lambda *_args: None)

    def run_test_suite(test_entries, expectation, container, repo_path):
        calls.append((test_entries, expectation, container, repo_path))
        raise TestExecutionError(TestExpectation.ANY_FAIL)

    monkeypatch.setattr("bcbench.evaluate.testgeneration.run_test_suite", run_test_suite)

    TestGenerationPipeline().evaluate(context)

    result_path = context.result_dir / f"{context.entry.instance_id}{get_config().file_patterns.result_pattern}"
    result = TestGenerationResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    assert calls == [(generated_tests, TestExpectation.ANY_FAIL, context.container, context.repo_path)]
    assert result.pre_patch_failed is False
    assert result.error_message is not None
    assert result.error_message.startswith("Generated tests Passed pre-patch")


def test_test_generation_non_any_fail_error_is_classified_as_post_patch(tmp_path, monkeypatch):
    context = create_evaluation_context(tmp_path, category=EvaluationCategory.TEST_GENERATION)
    generated_tests = [TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))]
    calls = 0

    monkeypatch.setattr("bcbench.evaluate.testgeneration.categorize_projects", lambda _paths: (["test"], ["app"]))
    monkeypatch.setattr("bcbench.evaluate.testgeneration.clean_project_paths", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.stage_and_get_diff", lambda _repo_path: "generated patch")
    monkeypatch.setattr("bcbench.evaluate.testgeneration.extract_file_paths_from_patch", lambda _patch: [])
    monkeypatch.setattr("bcbench.evaluate.testgeneration.extract_tests_from_patch", lambda *_args: generated_tests)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.build_and_publish_projects", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.apply_patch", lambda *_args: None)

    def run_test_suite(_test_entries, expectation, _container, _repo_path):
        nonlocal calls
        calls += 1
        if calls == 1:
            return TestRunSummary((), (), ())
        raise TestExecutionError(expectation)

    monkeypatch.setattr("bcbench.evaluate.testgeneration.run_test_suite", run_test_suite)

    TestGenerationPipeline().evaluate(context)

    result_path = context.result_dir / f"{context.entry.instance_id}{get_config().file_patterns.result_pattern}"
    result = TestGenerationResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    assert result.pre_patch_failed is True
    assert result.post_patch_passed is False
    assert result.error_message is not None
    assert result.error_message.startswith("Generated tests Failed post-patch")


def test_test_generation_persists_expectation_failure_diagnostics(tmp_path, monkeypatch):
    context = create_evaluation_context(tmp_path, category=EvaluationCategory.TEST_GENERATION)
    generated_tests = [TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))]
    calls = 0
    stdout = """\
Codeunit 50100 Regression Tests
    Testfunction RegressionTest Failure (0.25 seconds)
      Error:
        Assert.AreEqual failed. Expected:<1>. Actual:<2>.
"""

    monkeypatch.setattr("bcbench.evaluate.testgeneration.categorize_projects", lambda _paths: (["test"], ["app"]))
    monkeypatch.setattr("bcbench.evaluate.testgeneration.clean_project_paths", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.stage_and_get_diff", lambda _repo_path: "generated patch")
    monkeypatch.setattr("bcbench.evaluate.testgeneration.extract_file_paths_from_patch", lambda _patch: [])
    monkeypatch.setattr("bcbench.evaluate.testgeneration.extract_tests_from_patch", lambda *_args: generated_tests)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.build_and_publish_projects", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.apply_patch", lambda *_args: None)

    def run_test_suite(_test_entries, expectation, _container, _repo_path):
        nonlocal calls
        calls += 1
        if calls == 1:
            return TestRunSummary((), (), ())
        raise TestExecutionError(
            expectation,
            stdout=stdout,
            stderr="PowerShell assertion diagnostic",
            reason="Expected every test to pass, but 1 did not.",
        )

    monkeypatch.setattr("bcbench.evaluate.testgeneration.run_test_suite", run_test_suite)

    TestGenerationPipeline().evaluate(context)

    result_path = context.result_dir / f"{context.entry.instance_id}{get_config().file_patterns.result_pattern}"
    result = TestGenerationResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    assert result.error_message is not None
    assert "Testfunction RegressionTest Failure" in result.error_message
    assert "Assert.AreEqual failed" in result.error_message
    assert "Standard error:" in result.error_message
    assert "PowerShell assertion diagnostic" in result.error_message


def test_test_generation_persists_timeout_as_score_excluded_infrastructure_failure(tmp_path, monkeypatch):
    context = create_evaluation_context(tmp_path, category=EvaluationCategory.TEST_GENERATION)
    context.repo_path.mkdir(parents=True)
    generated_tests = [TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))]

    monkeypatch.setattr("bcbench.evaluate.testgeneration.categorize_projects", lambda _paths: (["test"], ["app"]))
    monkeypatch.setattr("bcbench.evaluate.testgeneration.clean_project_paths", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.stage_and_get_diff", lambda _repo_path: "generated patch")
    monkeypatch.setattr("bcbench.evaluate.testgeneration.extract_file_paths_from_patch", lambda _patch: [])
    monkeypatch.setattr("bcbench.evaluate.testgeneration.extract_tests_from_patch", lambda *_args: generated_tests)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.build_and_publish_projects", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.apply_patch", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.run_test_suite", bc_operations.run_test_suite)
    monkeypatch.setattr(
        bc_operations.subprocess,
        "run",
        lambda command, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(command, timeout=123)),
    )

    TestGenerationPipeline().evaluate(context)

    result_path = context.result_dir / f"{context.entry.instance_id}{get_config().file_patterns.result_pattern}"
    result = TestGenerationResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    summary = ExecutionBasedEvaluationResultSummary.from_results([result], run_id="test-run")
    assert result.infrastructure_failure is True
    assert result.error_message is not None
    assert "timed out" in result.error_message
    assert summary.infrastructure_failed == 1
    assert summary.failed == 0
    assert summary.instance_results == {}


@pytest.mark.parametrize(
    ("failing_expectation", "pre_patch_failed"),
    [
        (TestExpectation.ANY_FAIL, False),
        (TestExpectation.ALL_PASS, True),
    ],
)
def test_test_generation_persists_test_infrastructure_failure_without_claiming_test_outcome(
    tmp_path,
    monkeypatch,
    failing_expectation: TestExpectation,
    pre_patch_failed: bool,
):
    context = create_evaluation_context(tmp_path, category=EvaluationCategory.TEST_GENERATION)
    generated_tests = [TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))]

    monkeypatch.setattr("bcbench.evaluate.testgeneration.categorize_projects", lambda _paths: (["test"], ["app"]))
    monkeypatch.setattr("bcbench.evaluate.testgeneration.clean_project_paths", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.stage_and_get_diff", lambda _repo_path: "generated patch")
    monkeypatch.setattr("bcbench.evaluate.testgeneration.extract_file_paths_from_patch", lambda _patch: [])
    monkeypatch.setattr("bcbench.evaluate.testgeneration.extract_tests_from_patch", lambda *_args: generated_tests)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.build_and_publish_projects", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.testgeneration.apply_patch", lambda *_args: None)

    def run_test_suite(_test_entries, expectation, _container, _repo_path):
        if expectation is failing_expectation:
            raise TestInfrastructureError(
                expectation,
                reason="PowerShell exited before evidence validation",
                stdout="test execution output",
                stderr="pwsh failure detail",
            )

    monkeypatch.setattr("bcbench.evaluate.testgeneration.run_test_suite", run_test_suite)

    TestGenerationPipeline().evaluate(context)

    result_path = context.result_dir / f"{context.entry.instance_id}{get_config().file_patterns.result_pattern}"
    result = TestGenerationResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    assert result.resolved is False
    assert result.infrastructure_failure is True
    assert result.pre_patch_failed is pre_patch_failed
    assert result.post_patch_passed is False
    assert result.error_message is not None
    assert result.error_message.startswith("Test infrastructure failed")
    assert "PowerShell exited before evidence validation" in result.error_message
    assert "test execution output" in result.error_message
    assert "pwsh failure detail" in result.error_message
    assert "Generated tests Passed" not in result.error_message
    assert "Generated tests Failed" not in result.error_message
