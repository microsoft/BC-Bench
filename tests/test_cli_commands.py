"""Integration tests for CLI commands using Typer's CliRunner."""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.dataset import DatasetEntry
from bcbench.types import AgentMetrics
from tests.conftest import (
    create_bugfix_result,
    create_dataset_entry,
    create_dataset_file,
    create_test_entry,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def disable_github_actions(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    # Reset the config singleton to pick up the environment changes
    import bcbench.config

    bcbench.config._config = None


@pytest.fixture
def sample_dataset_file_for_cli(tmp_path):
    entries = [
        create_dataset_entry(
            instance_id="microsoftInternal__NAV-1",
            base_commit="a" * 40,
            project_paths=["App/W1/TestApp/app", "App/W1/TestApp/test"],
            fail_to_pass=[create_test_entry(codeunit_id=12345, function_names={"TestFunction1"})],
        ),
        create_dataset_entry(
            instance_id="microsoftInternal__NAV-2",
            base_commit="b" * 40,
            environment_setup_version="27.0",
            project_paths=["App/W1/AnotherApp/app", "App/W1/AnotherApp/test"],
            fail_to_pass=[create_test_entry(codeunit_id=67890, function_names={"TestFunction2"})],
        ),
        create_dataset_entry(
            instance_id="microsoftInternal__NAV-3",
            base_commit="c" * 40,
            project_paths=["App/W1/ThirdApp/app", "App/W1/ThirdApp/test"],
            fail_to_pass=[create_test_entry(codeunit_id=22222, function_names={"TestFunction3"})],
            pass_to_pass=[create_test_entry(codeunit_id=11111, function_names={"PassingTest"})],
        ),
    ]
    return create_dataset_file(tmp_path, entries)


@pytest.fixture
def sample_results_directory(tmp_path, sample_dataset_file_for_cli):
    run_id = "test_run_123"
    results_dir = tmp_path / run_id
    results_dir.mkdir(parents=True)

    result1 = create_bugfix_result(
        instance_id="microsoftInternal__NAV-1",
        project="W1/TestApp",
        resolved=True,
        metrics=AgentMetrics(execution_time=120.0, prompt_tokens=5000, completion_tokens=1000),
    )
    result1.save(results_dir, f"{result1.instance_id}.jsonl")

    result2 = create_bugfix_result(
        instance_id="microsoftInternal__NAV-2",
        project="W1/AnotherApp",
        resolved=False,
        error_message="Test failed",
        metrics=AgentMetrics(execution_time=80.0, prompt_tokens=3000, completion_tokens=500),
    )
    result2.save(results_dir, f"{result2.instance_id}.jsonl")

    result3 = create_bugfix_result(
        instance_id="microsoftInternal__NAV-3",
        project="W1/ThirdApp",
        resolved=True,
        metrics=AgentMetrics(execution_time=95.0, prompt_tokens=4200, completion_tokens=800),
    )
    result3.save(results_dir, f"{result3.instance_id}.jsonl")

    return tmp_path, run_id, sample_dataset_file_for_cli


@pytest.mark.integration
def test_result_summarize_creates_all_outputs(sample_results_directory, problem_statement_dir):
    base_path, run_id, dataset_path = sample_results_directory
    results_dir = base_path / run_id

    with patch.object(DatasetEntry, "problem_statement_dir", property(lambda self: problem_statement_dir)):
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
def test_result_summarize_verifies_summary_calculations(sample_results_directory, problem_statement_dir):
    base_path, run_id, dataset_path = sample_results_directory
    results_dir = base_path / run_id

    with patch.object(DatasetEntry, "problem_statement_dir", property(lambda self: problem_statement_dir)):
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
def test_result_summarize_with_custom_pattern(sample_results_directory, problem_statement_dir):
    base_path, run_id, dataset_path = sample_results_directory

    with patch.object(DatasetEntry, "problem_statement_dir", property(lambda self: problem_statement_dir)):
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
def test_dataset_list_displays_all_entries(sample_dataset_file_for_cli):
    result = runner.invoke(
        app,
        [
            "dataset",
            "list",
            "--dataset-path",
            str(sample_dataset_file_for_cli),
        ],
    )

    assert result.exit_code == 0
    assert "microsoftInternal__NAV-1" in result.stdout
    assert "microsoftInternal__NAV-2" in result.stdout
    assert "microsoftInternal__NAV-3" in result.stdout
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
    entry = create_dataset_entry(instance_id="microsoftInternal__NAV-100")
    dataset_path = create_dataset_file(tmp_path, [entry])

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
    assert "microsoftInternal__NAV-100" in result.stdout
    assert "Found 1 entry(ies)" in result.stdout


@pytest.mark.integration
def test_dataset_list_verifies_entry_format(sample_dataset_file_for_cli):
    result = runner.invoke(
        app,
        [
            "dataset",
            "list",
            "--dataset-path",
            str(sample_dataset_file_for_cli),
        ],
    )

    assert result.exit_code == 0
    # Should contain instance_id of first entry
    assert "microsoftInternal__NAV-1" in result.stdout


@pytest.fixture
def sample_leaderboard_and_summary(tmp_path):
    leaderboard_dir = tmp_path / "_data"
    leaderboard_dir.mkdir()
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"
    testgen_leaderboard_path = leaderboard_dir / "test-generation.json"
    summary_path = tmp_path / "summary.json"

    # Create bug-fix leaderboard with 2 entries
    bugfix_data = [
        {
            "total": 10,
            "resolved": 6,
            "failed": 4,
            "build": 9,
            "date": "2025-01-10",
            "model": "gpt-4o",
            "category": "bug-fix",
            "agent_name": "copilot",
            "average_duration": 120.5,
            "average_prompt_tokens": 5000.0,
            "average_completion_tokens": 1500.0,
            "github_run_id": "run_001",
            "experiment": {
                "mcp_servers": ["server1", "server2"],
                "custom_instructions": True,
                "custom_agent": None,
            },
        },
        {
            "total": 10,
            "resolved": 7,
            "failed": 3,
            "build": 10,
            "date": "2025-01-12",
            "model": "gpt-4o",
            "category": "bug-fix",
            "agent_name": "mini",
            "average_duration": 95.0,
            "average_prompt_tokens": 3500.0,
            "average_completion_tokens": 1000.0,
            "github_run_id": "run_003",
            "experiment": {
                "mcp_servers": None,
                "custom_instructions": False,
                "custom_agent": None,
            },
        },
    ]

    # Create test-generation leaderboard with 1 entry
    testgen_data = [
        {
            "total": 10,
            "resolved": 5,
            "failed": 5,
            "build": 8,
            "date": "2025-01-11",
            "model": "gpt-4-turbo",
            "category": "test-generation",
            "agent_name": "copilot",
            "average_duration": 110.0,
            "average_prompt_tokens": 4500.0,
            "average_completion_tokens": 1200.0,
            "github_run_id": "run_002",
            "experiment": {
                "mcp_servers": None,
                "custom_instructions": False,
                "custom_agent": None,
            },
        },
    ]

    with open(bugfix_leaderboard_path, "w") as f:
        json.dump(bugfix_data, f, indent=2)

    with open(testgen_leaderboard_path, "w") as f:
        json.dump(testgen_data, f, indent=2)

    # Create a new summary to update (updated copilot + gpt-4o + server1, server2)
    new_summary = {
        "total": 10,
        "resolved": 8,  # Improved from 6 to 8
        "failed": 2,
        "build": 10,  # Improved from 9 to 10
        "date": "2025-01-15",
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 130.0,
        "average_prompt_tokens": 5200.0,
        "average_completion_tokens": 1600.0,
        "github_run_id": "run_004",
        "experiment": {
            "mcp_servers": ["server1", "server2"],
            "custom_instructions": True,
            "custom_agent": None,
        },
    }

    with open(summary_path, "w") as f:
        json.dump(new_summary, f, indent=2)

    return leaderboard_dir, summary_path


@pytest.mark.integration
def test_result_update_replaces_existing_entry(sample_leaderboard_and_summary):
    leaderboard_dir, summary_path = sample_leaderboard_and_summary
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"

    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
        ],
    )

    assert result.exit_code == 0, f"Command failed:\nstdout: {result.stdout}\nstderr: {result.stderr}\nexception: {result.exception}"

    # Verify bug-fix leaderboard still has 2 entries (not 3)
    with open(bugfix_leaderboard_path) as f:
        updated_leaderboard = json.load(f)

    assert len(updated_leaderboard) == 2, "Should still have 2 entries (replaced, not added)"

    # Find the updated entry and verify it matches
    updated_entry = None
    for entry in updated_leaderboard:
        exp = entry.get("experiment", {})
        if entry["agent_name"] == "copilot" and entry["model"] == "gpt-4o" and exp.get("mcp_servers") == ["server1", "server2"] and exp.get("custom_instructions") is True:
            updated_entry = entry
            break

    assert updated_entry is not None, "Should find the updated copilot + gpt-4o + server1, server2 entry"
    assert updated_entry["resolved"] == 8, "Should have updated resolved count"
    assert updated_entry["build"] == 10, "Should have updated build count"
    assert updated_entry["average_prompt_tokens"] == 5200.0, "Should have updated average_prompt_tokens"
    assert updated_entry["github_run_id"] == "run_004", "Should have updated github_run_id"


@pytest.mark.integration
def test_result_update_adds_new_entry(sample_leaderboard_and_summary):
    leaderboard_dir, _ = sample_leaderboard_and_summary
    summary_path = leaderboard_dir.parent / "new_agent_summary.json"

    # Create a new summary for a different agent
    new_summary = {
        "total": 10,
        "resolved": 9,
        "failed": 1,
        "build": 10,
        "date": "2025-01-16",
        "model": "gpt-4o",
        "category": "test-generation",
        "agent_name": "new-agent",
        "average_duration": 100.0,
        "average_prompt_tokens": 4800.0,
        "average_completion_tokens": 1400.0,
        "github_run_id": "run_005",
        "experiment": {
            "mcp_servers": None,
            "custom_instructions": False,
            "custom_agent": None,
        },
    }

    with open(summary_path, "w") as f:
        json.dump(new_summary, f, indent=2)

    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
        ],
    )

    assert result.exit_code == 0

    # Verify leaderboard now has 2 entries in test-generation
    with open(leaderboard_dir / "test-generation.json") as f:
        updated_leaderboard = json.load(f)

    assert len(updated_leaderboard) == 2, "Should now have 2 entries (added new in test-generation)"

    # Find the new entry
    new_entry = None
    for entry in updated_leaderboard:
        if entry["agent_name"] == "new-agent" and entry["model"] == "gpt-4o":
            new_entry = entry
            break

    assert new_entry is not None, "Should find the new entry for new-agent"
    assert new_entry["resolved"] == 9, "Should have correct resolved count"


@pytest.mark.integration
def test_result_update_distinguishes_by_mcp_servers(sample_leaderboard_and_summary):
    leaderboard_dir, _ = sample_leaderboard_and_summary
    summary_path = leaderboard_dir.parent / "copilot_different_mcp_summary.json"

    # Create a new summary for copilot + gpt-4o but WITHOUT mcp_servers (different from existing)
    new_summary = {
        "total": 10,
        "resolved": 7,
        "failed": 3,
        "build": 9,
        "date": "2025-01-17",
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 115.0,
        "average_prompt_tokens": 4900.0,
        "average_completion_tokens": 1350.0,
        "github_run_id": "run_006",
        "experiment": {
            "mcp_servers": None,  # Different from existing ["server1", "server2"]
            "custom_instructions": False,  # Different from existing True
            "custom_agent": None,
        },
    }

    with open(summary_path, "w") as f:
        json.dump(new_summary, f, indent=2)

    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
        ],
    )

    assert result.exit_code == 0

    # Verify bug-fix leaderboard now has 3 entries (not replaced because mcp_servers differ)
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"
    with open(bugfix_leaderboard_path) as f:
        updated_leaderboard = json.load(f)

    assert len(updated_leaderboard) == 3, "Should have 3 entries in bug-fix (added new because mcp_servers differ)"

    # Verify both copilot + gpt-4o entries exist
    copilot_gpt4o_entries = [e for e in updated_leaderboard if e["agent_name"] == "copilot" and e["model"] == "gpt-4o"]

    assert len(copilot_gpt4o_entries) == 2, "Should have 2 different copilot + gpt-4o entries"

    # Find each by experiment.mcp_servers
    with_servers = next((e for e in copilot_gpt4o_entries if e.get("experiment", {}).get("mcp_servers") == ["server1", "server2"]), None)
    without_servers = next((e for e in copilot_gpt4o_entries if e.get("experiment", {}).get("mcp_servers") is None), None)

    assert with_servers is not None and without_servers is not None
    assert with_servers["resolved"] == 6, "Original entry should be unchanged"
    assert without_servers["resolved"] == 7, "New entry should have new values"


@pytest.mark.integration
def test_result_update_ensures_newline_at_end_of_file(sample_leaderboard_and_summary):
    leaderboard_dir, summary_path = sample_leaderboard_and_summary

    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
        ],
    )

    assert result.exit_code == 0

    # Verify file ends with newline
    with open(leaderboard_dir / "bug-fix.json", "rb") as f:
        content = f.read()
        assert content.endswith(b"\n"), "Leaderboard file should end with a newline character"


@pytest.mark.integration
def test_result_update_does_not_add_multiple_newlines_when_run_twice(sample_leaderboard_and_summary):
    leaderboard_dir, summary_path = sample_leaderboard_and_summary

    # Run update command first time
    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
        ],
    )
    assert result.exit_code == 0

    # Read file after first update
    with open(leaderboard_dir / "bug-fix.json", "rb") as f:
        content_after_first = f.read()

    # Count trailing newlines after first update
    trailing_newlines_first = len(content_after_first) - len(content_after_first.rstrip(b"\n"))
    assert trailing_newlines_first == 1, "File should have exactly 1 trailing newline after first update"

    # Run update command second time with same summary
    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
        ],
    )
    assert result.exit_code == 0

    # Read file after second update
    with open(leaderboard_dir / "bug-fix.json", "rb") as f:
        content_after_second = f.read()

    # Count trailing newlines after second update
    trailing_newlines_second = len(content_after_second) - len(content_after_second.rstrip(b"\n"))
    assert trailing_newlines_second == 1, "File should still have exactly 1 trailing newline after second update, not 2"
