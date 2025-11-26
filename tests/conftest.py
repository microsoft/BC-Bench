"""
Shared test fixtures for BC-Bench tests.

This module provides reusable fixtures that create valid DatasetEntry objects
meeting all Pydantic validation requirements.
"""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.dataset import DatasetEntry, TestEntry
from bcbench.results.bugfix import BugFixResult
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import AgentMetrics, EvaluationCategory, EvaluationContext

# Valid test data that passes all DatasetEntry validation rules
VALID_INSTANCE_ID = "microsoftInternal__NAV-123456"
VALID_REPO = "microsoftInternal/NAV"
VALID_BASE_COMMIT = "a" * 40  # 40-character hex string
VALID_ENVIRONMENT_VERSION = "26.5"  # Pattern: XX.X
VALID_PATCH = "diff --git a/test.al b/test.al\n+test line"
VALID_TEST_PATCH = "diff --git a/test.al b/test.al\n+test"
VALID_CREATED_AT = "2025-01-15"
# Must have at least 2 project paths per validation rule
VALID_PROJECT_PATHS = ["App\\Apps\\W1\\Shopify\\app", "App\\Apps\\W1\\Shopify\\test"]

# Default problem statement content
PROBLEM_STATEMENT_CONTENT = "# Test Problem Statement\n\nThis is a test task."


def create_test_entry(codeunit_id: int = 100, function_names: set[str] | None = None) -> TestEntry:
    if function_names is None:
        function_names = {"TestFunction"}
    return TestEntry(codeunitID=codeunit_id, functionName=function_names)


def create_dataset_entry(
    instance_id: str = VALID_INSTANCE_ID,
    repo: str = VALID_REPO,
    base_commit: str = VALID_BASE_COMMIT,
    environment_setup_version: str = VALID_ENVIRONMENT_VERSION,
    project_paths: list[str] | None = None,
    patch: str = VALID_PATCH,
    test_patch: str = VALID_TEST_PATCH,
    created_at: str = VALID_CREATED_AT,
    fail_to_pass: list[TestEntry] | None = None,
    pass_to_pass: list[TestEntry] | None = None,
) -> DatasetEntry:
    if project_paths is None:
        project_paths = VALID_PROJECT_PATHS.copy()
    if fail_to_pass is None:
        fail_to_pass = [create_test_entry()]
    if pass_to_pass is None:
        pass_to_pass = []

    return DatasetEntry(
        instance_id=instance_id,
        repo=repo,
        base_commit=base_commit,
        environment_setup_version=environment_setup_version,
        project_paths=project_paths,
        patch=patch,
        test_patch=test_patch,
        created_at=created_at,
        fail_to_pass=fail_to_pass,
        pass_to_pass=pass_to_pass,
    )


def create_evaluation_context(
    tmp_path: Path,
    entry: DatasetEntry | None = None,
    agent_name: str = "test-agent",
    model: str = "test-model",
    category: EvaluationCategory = EvaluationCategory.BUG_FIX,
    container_name: str = "test-container",
    password: str = "test-password",
    username: str = "test-user",
) -> EvaluationContext:
    if entry is None:
        entry = create_dataset_entry()

    return EvaluationContext(
        entry=entry,
        repo_path=tmp_path / "repo",
        result_dir=tmp_path / "results",
        container_name=container_name,
        password=password,
        username=username,
        agent_name=agent_name,
        model=model,
        category=category,
    )


def create_bugfix_result(
    instance_id: str = VALID_INSTANCE_ID,
    project: str = "Shopify",
    model: str = "gpt-4o",
    agent_name: str = "copilot-cli",
    resolved: bool = True,
    build: bool = True,
    generated_patch: str = "diff --git a/test.al b/test.al\n+fixed",
    error_message: str | None = None,
    metrics: AgentMetrics | None = None,
) -> BugFixResult:
    return BugFixResult(
        instance_id=instance_id,
        project=project,
        model=model,
        agent_name=agent_name,
        category=EvaluationCategory.BUG_FIX,
        resolved=resolved,
        build=build,
        generated_patch=generated_patch,
        error_message=error_message,
        metrics=metrics,
    )


def create_testgen_result(
    instance_id: str = VALID_INSTANCE_ID,
    project: str = "Shopify",
    model: str = "gpt-4o",
    agent_name: str = "copilot-cli",
    resolved: bool = False,
    build: bool = True,
    generated_patch: str = "diff --git a/test.al b/test.al\n+test",
    error_message: str | None = None,
    metrics: AgentMetrics | None = None,
    pre_patch_failed: bool | None = None,
    post_patch_passed: bool | None = None,
) -> TestGenerationResult:
    return TestGenerationResult(
        instance_id=instance_id,
        project=project,
        model=model,
        agent_name=agent_name,
        category=EvaluationCategory.TEST_GENERATION,
        resolved=resolved,
        build=build,
        generated_patch=generated_patch,
        error_message=error_message,
        metrics=metrics,
        pre_patch_failed=pre_patch_failed,
        post_patch_passed=post_patch_passed,
    )


def create_dataset_file(tmp_path: Path, entries: list[DatasetEntry] | None = None) -> Path:
    if entries is None:
        entries = [create_dataset_entry()]

    dataset_path = tmp_path / "dataset.jsonl"
    with open(dataset_path, "w") as f:
        for entry in entries:
            entry_dict = {
                "instance_id": entry.instance_id,
                "repo": entry.repo,
                "base_commit": entry.base_commit,
                "environment_setup_version": entry.environment_setup_version,
                "FAIL_TO_PASS": [{"codeunitID": t.codeunitID, "functionName": list(t.functionName)} for t in entry.fail_to_pass],
                "PASS_TO_PASS": [{"codeunitID": t.codeunitID, "functionName": list(t.functionName)} for t in entry.pass_to_pass],
                "project_paths": entry.project_paths,
                "patch": entry.patch,
                "test_patch": entry.test_patch,
                "created_at": entry.created_at,
            }
            f.write(json.dumps(entry_dict) + "\n")
    return dataset_path


def create_problem_statement_dir(tmp_path: Path, content: str = PROBLEM_STATEMENT_CONTENT) -> Path:
    problem_dir = tmp_path / "problem_statement"
    problem_dir.mkdir(parents=True, exist_ok=True)
    readme_file = problem_dir / "README.md"
    readme_file.write_text(content, encoding="utf-8")
    return problem_dir


@pytest.fixture
def sample_test_entry() -> TestEntry:
    return create_test_entry()


@pytest.fixture
def sample_dataset_entry() -> DatasetEntry:
    return create_dataset_entry()


@pytest.fixture
def sample_evaluation_context(tmp_path: Path) -> EvaluationContext:
    return create_evaluation_context(tmp_path)


@pytest.fixture
def problem_statement_dir(tmp_path: Path) -> Path:
    return create_problem_statement_dir(tmp_path)


@pytest.fixture
def sample_dataset_file(tmp_path: Path) -> Path:
    return create_dataset_file(tmp_path)


@pytest.fixture
def sample_bugfix_result() -> BugFixResult:
    return create_bugfix_result()


@pytest.fixture
def sample_testgen_result() -> TestGenerationResult:
    return create_testgen_result()


@pytest.fixture
def sample_bugfix_result_with_metrics() -> BugFixResult:
    return create_bugfix_result(
        metrics=AgentMetrics(execution_time=120.5, prompt_tokens=5000, completion_tokens=1200),
    )


@pytest.fixture
def sample_dataset_entry_with_problem_statement(tmp_path: Path) -> Generator[DatasetEntry, None, None]:
    problem_dir = create_problem_statement_dir(tmp_path)
    entry = create_dataset_entry()

    # Patch the problem_statement_dir property to return our temp directory
    with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
        yield entry
