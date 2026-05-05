"""
Shared test fixtures for BC-Bench tests.

This module provides reusable fixtures that create valid BugFixEntry objects
meeting all Pydantic validation requirements.
"""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.dataset import BugFixEntry, NL2ALEntry, TestEntry
from bcbench.dataset.dataset_entry import _BugFixTestGenBase
from bcbench.results.bugfix import BugFixResult
from bcbench.results.nl2al import NL2ALResult
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import AgentMetrics, ContainerConfig, EvaluationCategory, EvaluationContext

# Valid test data that passes all BugFixEntry validation rules
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
    return TestEntry(codeunitID=codeunit_id, functionName=frozenset(function_names))


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
) -> BugFixEntry:
    if project_paths is None:
        project_paths = VALID_PROJECT_PATHS.copy()
    if fail_to_pass is None:
        fail_to_pass = [create_test_entry()]
    if pass_to_pass is None:
        pass_to_pass = []

    return BugFixEntry(
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
    entry: BugFixEntry | None = None,
    agent_name: str = "test-agent",
    model: str = "test-model",
    category: EvaluationCategory = EvaluationCategory.BUG_FIX,
    container_name: str = "test-container",
    password: str = "test-password",
    username: str = "test-user",
) -> EvaluationContext[BugFixEntry]:
    if entry is None:
        entry = create_dataset_entry()

    return EvaluationContext[BugFixEntry](
        entry=entry,
        repo_path=tmp_path / "repo",
        result_dir=tmp_path / "results",
        container=ContainerConfig(name=container_name, username=username, password=password),
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
    output: str = "diff --git a/test.al b/test.al\n+fixed",
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
        output=output,
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
    output: str = "diff --git a/test.al b/test.al\n+test",
    error_message: str | None = None,
    metrics: AgentMetrics | None = None,
    pre_patch_failed: bool = False,
    post_patch_passed: bool = False,
) -> TestGenerationResult:
    return TestGenerationResult(
        instance_id=instance_id,
        project=project,
        model=model,
        agent_name=agent_name,
        category=EvaluationCategory.TEST_GENERATION,
        resolved=resolved,
        build=build,
        output=output,
        error_message=error_message,
        metrics=metrics,
        pre_patch_failed=pre_patch_failed,
        post_patch_passed=post_patch_passed,
    )


def create_dataset_file(tmp_path: Path, entries: list[BugFixEntry] | None = None) -> Path:
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
def sample_dataset_entry() -> BugFixEntry:
    return create_dataset_entry()


@pytest.fixture
def sample_evaluation_context(tmp_path: Path) -> EvaluationContext[BugFixEntry]:
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
        metrics=AgentMetrics(execution_time=120.5, prompt_tokens=5000, completion_tokens=1200, llm_duration=100.0, tool_usage={"view_code": 2, "run_tests": 1}),
    )


@pytest.fixture
def sample_dataset_entry_with_problem_statement(tmp_path: Path) -> Generator[BugFixEntry]:
    problem_dir = create_problem_statement_dir(tmp_path)
    entry = create_dataset_entry()

    with patch.object(_BugFixTestGenBase, "problem_statement_dir", property(lambda self: problem_dir)):
        yield entry


VALID_NL_PROMPT = "Create a report showing budgeted cost vs actual cost broken down by job task."


def create_nl2al_entry(
    instance_id: str = "nl2al__job-budget-report-1",
    repo: str = "nl2al/template",
    environment_setup_version: str = VALID_ENVIRONMENT_VERSION,
    project_paths: list[str] | None = None,
    patch: str = VALID_PATCH,
    nl_prompt: str = VALID_NL_PROMPT,
    created_at: str = VALID_CREATED_AT,
) -> NL2ALEntry:
    if project_paths is None:
        project_paths = ["JobBudgetVsActualReport"]

    return NL2ALEntry(
        instance_id=instance_id,
        repo=repo,
        base_commit=None,
        environment_setup_version=environment_setup_version,
        project_paths=project_paths,
        patch=patch,
        nl_prompt=nl_prompt,
        created_at=created_at,
    )


def create_nl2al_result(
    instance_id: str = "nl2al__job-budget-report-1",
    project: str = "JobBudgetVsActualReport",
    model: str = "gpt-4o",
    agent_name: str = "copilot-cli",
    build: bool = True,
    output: str = "diff --git a/test.al b/test.al\n+report code",
    error_message: str | None = None,
    metrics: AgentMetrics | None = None,
) -> NL2ALResult:
    return NL2ALResult(
        instance_id=instance_id,
        project=project,
        model=model,
        agent_name=agent_name,
        category=EvaluationCategory.NL2AL,
        build=build,
        output=output,
        error_message=error_message,
        metrics=metrics,
    )


@pytest.fixture
def sample_nl2al_entry() -> NL2ALEntry:
    return create_nl2al_entry()


@pytest.fixture
def sample_nl2al_result() -> NL2ALResult:
    return create_nl2al_result()
