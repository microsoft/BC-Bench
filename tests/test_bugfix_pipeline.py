from collections.abc import Callable

import pytest

from bcbench.config import get_config
from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix import BugFixPipeline
from bcbench.exceptions import NoTestsExtractedError, TestExecutionError
from bcbench.results.bugfix import BugFixResult
from tests.conftest import create_evaluation_context


def _read_result(context) -> BugFixResult:
    result_file = context.result_dir / f"{context.entry.instance_id}{get_config().file_patterns.result_pattern}"
    return BugFixResult.model_validate_json(result_file.read_text(encoding="utf-8"))


def _configure_successful_evaluation(monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], list[str]]:
    applied_patches: list[str] = []
    test_expectations: list[str] = []

    monkeypatch.setattr("bcbench.evaluate.bugfix.stage_and_get_diff", lambda _repo_path: "full patch")
    monkeypatch.setattr("bcbench.evaluate.bugfix.separate_patches", lambda *_args: ("full patch", "fix patch", "test patch"))
    monkeypatch.setattr("bcbench.evaluate.bugfix.extract_file_paths_from_patch", lambda _patch: [])
    monkeypatch.setattr(
        "bcbench.evaluate.bugfix.extract_tests_from_patch",
        lambda *_args: [TestEntry(codeunitID=123, functionName=frozenset({"RegressionTest"}))],
    )
    monkeypatch.setattr("bcbench.evaluate.bugfix.clean_project_paths", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.bugfix.build_and_publish_projects", lambda *_args: None)
    monkeypatch.setattr(
        "bcbench.evaluate.bugfix.apply_patch",
        lambda _repo_path, _patch, patch_name: applied_patches.append(patch_name),
    )
    monkeypatch.setattr(
        "bcbench.evaluate.bugfix.run_test_suite",
        lambda _tests, expectation, _container: test_expectations.append(expectation),
    )
    monkeypatch.setattr("bcbench.evaluate.bugfix.run_tests", lambda *_args: None)
    return applied_patches, test_expectations


def test_bugfix_requires_generated_test_and_hidden_test_to_pass(tmp_path, monkeypatch):
    context = create_evaluation_context(tmp_path)
    applied_patches, test_expectations = _configure_successful_evaluation(monkeypatch)

    BugFixPipeline().evaluate(context)

    result = _read_result(context)
    assert result.resolved is True
    assert result.generated_test_pre_patch_failed is True
    assert result.generated_test_post_patch_passed is True
    assert result.benchmark_test_passed is True
    assert test_expectations == ["Fail", "Pass"]
    assert applied_patches == [
        f"{context.entry.instance_id} generated fix patch",
        f"{context.entry.instance_id} benchmark test patch",
    ]


def test_bugfix_rejects_patch_without_generated_test(tmp_path, monkeypatch):
    context = create_evaluation_context(tmp_path)
    monkeypatch.setattr("bcbench.evaluate.bugfix.stage_and_get_diff", lambda _repo_path: "full patch")
    monkeypatch.setattr("bcbench.evaluate.bugfix.separate_patches", lambda *_args: ("full patch", "fix patch", ""))
    monkeypatch.setattr("bcbench.evaluate.bugfix.extract_file_paths_from_patch", lambda _patch: [])
    monkeypatch.setattr(
        "bcbench.evaluate.bugfix.extract_tests_from_patch",
        lambda *_args: (_ for _ in ()).throw(NoTestsExtractedError()),
    )

    BugFixPipeline().evaluate(context)

    result = _read_result(context)
    assert result.resolved is False
    assert result.build is False
    assert result.error_message == "No tests extracted from the generated patch."


@pytest.mark.parametrize(
    ("failing_call", "error_prefix", "pre_patch_failed", "post_patch_passed"),
    [
        (
            lambda expectation, _call_index: expectation == "Fail",
            "Generated tests passed before the product-code fix",
            False,
            False,
        ),
        (
            lambda expectation, _call_index: expectation == "Pass",
            "Generated tests failed after the product-code fix",
            True,
            False,
        ),
    ],
)
def test_bugfix_rejects_invalid_generated_test_transition(
    tmp_path,
    monkeypatch,
    failing_call: Callable[[str, int], bool],
    error_prefix: str,
    pre_patch_failed: bool,
    post_patch_passed: bool,
):
    context = create_evaluation_context(tmp_path)
    _configure_successful_evaluation(monkeypatch)
    call_index = 0

    def run_generated_tests(_tests, expectation, _container):
        nonlocal call_index
        call_index += 1
        if failing_call(expectation, call_index):
            raise TestExecutionError(expectation)

    monkeypatch.setattr("bcbench.evaluate.bugfix.run_test_suite", run_generated_tests)

    BugFixPipeline().evaluate(context)

    result = _read_result(context)
    assert result.resolved is False
    assert result.generated_test_pre_patch_failed is pre_patch_failed
    assert result.generated_test_post_patch_passed is post_patch_passed
    assert result.benchmark_test_passed is False
    assert result.error_message is not None
    assert result.error_message.startswith(error_prefix)


def test_bugfix_rejects_fix_when_benchmark_test_fails(tmp_path, monkeypatch):
    context = create_evaluation_context(tmp_path)
    _configure_successful_evaluation(monkeypatch)
    monkeypatch.setattr(
        "bcbench.evaluate.bugfix.run_tests",
        lambda *_args: (_ for _ in ()).throw(TestExecutionError("Pass")),
    )

    BugFixPipeline().evaluate(context)

    result = _read_result(context)
    assert result.resolved is False
    assert result.generated_test_pre_patch_failed is True
    assert result.generated_test_post_patch_passed is True
    assert result.benchmark_test_passed is False
    assert result.error_message is not None
    assert result.error_message.startswith("Benchmark tests failed after the generated fix")
