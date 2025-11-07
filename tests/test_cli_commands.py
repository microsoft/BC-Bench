"""Integration tests for CLI commands using Typer's CliRunner."""

import json

import pytest
from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.results import EvaluationResult

runner = CliRunner()


@pytest.fixture(autouse=True)
def disable_github_actions(monkeypatch):
    """Automatically disable GitHub Actions environment for all CLI tests."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    # Reset the config singleton to pick up the environment changes
    import bcbench.config

    bcbench.config._config = None


@pytest.fixture
def sample_dataset_file(tmp_path):
    dataset_path = tmp_path / "test_dataset.jsonl"

    entries = [
        {
            "instance_id": "test__entry-1",
            "repo": "microsoftInternal/NAV",
            "base_commit": "abc123",
            "created_at": "2025-01-15",
            "environment_setup_version": "26.5",
            "project_paths": ["App/W1/TestApp"],
            "problem_statement": "Test issue 1",
            "patch": "diff --git a/test.al b/test.al\n+new line",
            "test_patch": "",
            "FAIL_TO_PASS": [{"codeunitID": 12345, "functionName": ["TestFunction1"]}],
            "PASS_TO_PASS": [],
        },
        {
            "instance_id": "test__entry-2",
            "repo": "microsoftInternal/NAV",
            "base_commit": "def456",
            "created_at": "2025-01-20",
            "environment_setup_version": "27.0",
            "project_paths": ["App/W1/AnotherApp"],
            "problem_statement": "Test issue 2",
            "patch": "diff --git a/test2.al b/test2.al\n+another line",
            "test_patch": "",
            "FAIL_TO_PASS": [{"codeunitID": 67890, "functionName": ["TestFunction2"]}],
            "PASS_TO_PASS": [],
        },
        {
            "instance_id": "test__entry-3",
            "repo": "microsoftInternal/NAV",
            "base_commit": "ghi789",
            "created_at": "2025-02-01",
            "environment_setup_version": "26.5",
            "project_paths": ["App/W1/ThirdApp"],
            "problem_statement": "Test issue 3",
            "patch": "diff --git a/test3.al b/test3.al\n+third line",
            "test_patch": "",
            "FAIL_TO_PASS": [],
            "PASS_TO_PASS": [{"codeunitID": 11111, "functionName": ["PassingTest"]}],
        },
    ]

    with open(dataset_path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    return dataset_path


@pytest.fixture
def sample_results_directory(tmp_path, sample_dataset_file):
    run_id = "test_run_123"
    results_dir = tmp_path / run_id
    results_dir.mkdir(parents=True)

    # Create sample results
    result1 = EvaluationResult(
        instance_id="test__entry-1",
        project="W1/TestApp",
        model="gpt-4o",
        agent_name="test-agent",
        resolved=True,
        build=True,
        generated_patch="diff --git a/test.al b/test.al\n+fixed line",
        agent_execution_time=120.0,
        prompt_tokens=5000,
        completion_tokens=1000,
    )
    result1.save(results_dir, f"{result1.instance_id}.jsonl")

    result2 = EvaluationResult(
        instance_id="test__entry-2",
        project="W1/AnotherApp",
        model="gpt-4o",
        agent_name="test-agent",
        resolved=False,
        build=True,
        error_message="Test failed",
        agent_execution_time=80.0,
        prompt_tokens=3000,
        completion_tokens=500,
    )
    result2.save(results_dir, f"{result2.instance_id}.jsonl")

    result3 = EvaluationResult(
        instance_id="test__entry-3",
        project="W1/ThirdApp",
        model="gpt-4o",
        agent_name="test-agent",
        resolved=True,
        build=True,
        generated_patch="diff --git a/test3.al b/test3.al\n+another fix",
        agent_execution_time=95.0,
        prompt_tokens=4200,
        completion_tokens=800,
    )
    result3.save(results_dir, f"{result3.instance_id}.jsonl")

    return tmp_path, run_id, sample_dataset_file


@pytest.mark.integration
def test_result_summarize_creates_all_outputs(sample_results_directory):
    base_path, run_id, dataset_path = sample_results_directory
    results_dir = base_path / run_id

    result = runner.invoke(
        app,
        [
            "result",
            "summarize",
            "--run-id",
            run_id,
            "--result-dir",
            str(base_path),
            "--dataset-path",
            str(dataset_path),
        ],
    )

    assert result.exit_code == 0, f"Command failed:\nstdout: {result.stdout}\nstderr: {result.stderr}\nexception: {result.exception}"
    assert (results_dir / "bceval_results.jsonl").exists()
    assert (results_dir / "evaluation_summary.json").exists()

    summary = json.loads((results_dir / "evaluation_summary.json").read_text())
    assert summary["total"] == 3
    assert summary["resolved"] == 2
    assert summary["failed"] == 1
    assert summary["build"] == 3


@pytest.mark.integration
def test_result_summarize_verifies_summary_calculations(sample_results_directory):
    base_path, run_id, dataset_path = sample_results_directory
    results_dir = base_path / run_id

    result = runner.invoke(
        app,
        [
            "result",
            "summarize",
            "--run-id",
            run_id,
            "--result-dir",
            str(base_path),
            "--dataset-path",
            str(dataset_path),
        ],
    )

    assert result.exit_code == 0

    summary = json.loads((results_dir / "evaluation_summary.json").read_text())

    # Verify averages (120 + 80 + 95) / 3 = 98.33...
    assert "average_duration" in summary
    assert summary["average_duration"] > 98.0
    assert summary["average_duration"] < 99.0

    # Verify token averages
    assert "average_prompt_tokens" in summary
    assert "average_completion_tokens" in summary


@pytest.mark.integration
def test_result_summarize_missing_directory_fails_gracefully(tmp_path):
    """Integration test: result summarize fails gracefully when run_id doesn't exist."""
    result = runner.invoke(
        app,
        [
            "result",
            "summarize",
            "--run-id",
            "nonexistent_run",
            "--result-dir",
            str(tmp_path),
        ],
    )

    # Command should exit with error code 1 when directory doesn't exist
    assert result.exit_code == 1


@pytest.mark.integration
def test_result_summarize_no_matching_files_fails_gracefully(tmp_path):
    run_id = "empty_run"
    results_dir = tmp_path / run_id
    results_dir.mkdir(parents=True)

    # Create a file that doesn't match the expected pattern
    (results_dir / "random_file.txt").write_text("not a result")

    result = runner.invoke(
        app,
        [
            "result",
            "summarize",
            "--run-id",
            run_id,
            "--result-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1


@pytest.mark.integration
def test_result_summarize_with_custom_pattern(sample_results_directory):
    base_path, run_id, dataset_path = sample_results_directory

    result = runner.invoke(
        app,
        [
            "result",
            "summarize",
            "--run-id",
            run_id,
            "--result-dir",
            str(base_path),
            "--dataset-path",
            str(dataset_path),
            "--result-pattern",
            "*.jsonl",
        ],
    )

    assert result.exit_code == 0


@pytest.mark.integration
def test_dataset_list_displays_all_entries(sample_dataset_file):
    result = runner.invoke(
        app,
        [
            "dataset",
            "list",
            "--dataset-path",
            str(sample_dataset_file),
        ],
    )

    assert result.exit_code == 0
    assert "test__entry-1" in result.stdout
    assert "test__entry-2" in result.stdout
    assert "test__entry-3" in result.stdout
    assert "Found 3 entry(ies)" in result.stdout


@pytest.mark.integration
def test_dataset_list_missing_file_fails_gracefully(tmp_path):
    nonexistent_path = tmp_path / "nonexistent.jsonl"

    result = runner.invoke(
        app,
        [
            "dataset",
            "list",
            "--dataset-path",
            str(nonexistent_path),
        ],
    )

    assert result.exit_code != 0


@pytest.mark.integration
def test_dataset_list_empty_file_shows_zero_entries(tmp_path):
    empty_dataset = tmp_path / "empty.jsonl"
    empty_dataset.write_text("")

    result = runner.invoke(
        app,
        [
            "dataset",
            "list",
            "--dataset-path",
            str(empty_dataset),
        ],
    )

    assert result.exit_code == 0
    assert "Found 0 entry(ies)" in result.stdout


@pytest.mark.integration
def test_dataset_list_single_entry(tmp_path):
    dataset_path = tmp_path / "single_entry.jsonl"

    entry = {
        "instance_id": "test__only-one",
        "repo": "microsoftInternal/NAV",
        "base_commit": "abc123",
        "created_at": "2025-01-15",
        "environment_setup_version": "26.5",
        "project_paths": ["App/W1/TestApp"],
        "problem_statement": "Single test issue",
        "patch": "diff --git a/test.al b/test.al\n+line",
        "test_patch": "",
        "FAIL_TO_PASS": [],
        "PASS_TO_PASS": [],
    }

    with open(dataset_path, "w") as f:
        f.write(json.dumps(entry) + "\n")

    result = runner.invoke(
        app,
        [
            "dataset",
            "list",
            "--dataset-path",
            str(dataset_path),
        ],
    )

    assert result.exit_code == 0
    assert "test__only-one" in result.stdout
    assert "Found 1 entry(ies)" in result.stdout


@pytest.mark.integration
def test_dataset_list_verifies_entry_format(sample_dataset_file):
    # This test ensures that the CLI can read and parse the dataset
    # without throwing JSON errors
    result = runner.invoke(
        app,
        [
            "dataset",
            "list",
            "--dataset-path",
            str(sample_dataset_file),
        ],
    )

    assert result.exit_code == 0
    # Should contain instance_id of first entry
    assert "test__entry-1" in result.stdout
