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

    # Create bug-fix leaderboard with 2 runs from different agents
    # Generate instance_results for pass^k calculation
    copilot_instance_results = {f"test__inst_{i}": (i < 6) for i in range(10)}  # 6 resolved
    mini_instance_results = {f"test__inst_{i}": (i < 7) for i in range(10)}  # 7 resolved

    bugfix_data = {
        "runs": [
            {
                "total": 10,
                "resolved": 6,
                "failed": 4,
                "build": 9,
                "percentage": 60.0,
                "date": "2025-01-10",
                "model": "gpt-4o",
                "category": "bug-fix",
                "agent_name": "copilot",
                "average_duration": 120.5,
                "average_prompt_tokens": 5000.0,
                "average_completion_tokens": 1500.0,
                "average_llm_duration": 80.0,
                "github_run_id": "run_001",
                "experiment": {
                    "mcp_servers": ["server1", "server2"],
                    "custom_instructions": True,
                    "custom_agent": None,
                },
                "instance_results": copilot_instance_results,
            },
            {
                "total": 10,
                "resolved": 7,
                "failed": 3,
                "build": 10,
                "percentage": 70.0,
                "date": "2025-01-12",
                "model": "gpt-4o",
                "category": "bug-fix",
                "agent_name": "mini",
                "average_duration": 95.0,
                "average_prompt_tokens": 3500.0,
                "average_completion_tokens": 1000.0,
                "average_llm_duration": 65.0,
                "github_run_id": "run_003",
                "experiment": {
                    "mcp_servers": None,
                    "custom_instructions": False,
                    "custom_agent": None,
                },
                "instance_results": mini_instance_results,
            },
        ],
        "aggregate": [
            {
                "model": "gpt-4o",
                "agent_name": "copilot",
                "category": "bug-fix",
                "experiment": {
                    "mcp_servers": ["server1", "server2"],
                    "custom_instructions": True,
                    "custom_agent": None,
                },
                "total": 10,
                "num_runs": 1,
                "average_duration": 120.5,
                "pass_hat_1": 0.6,
                "pass_hat_3": None,
                "pass_hat_5": None,
            },
            {
                "model": "gpt-4o",
                "agent_name": "mini",
                "category": "bug-fix",
                "experiment": None,
                "total": 10,
                "num_runs": 1,
                "average_duration": 95.0,
                "pass_hat_1": 0.7,
                "pass_hat_3": None,
                "pass_hat_5": None,
            },
        ],
    }

    # Create test-generation leaderboard with 1 entry
    testgen_instance_results = {f"test__inst_{i}": (i < 5) for i in range(10)}  # 5 resolved

    testgen_data = {
        "runs": [
            {
                "total": 10,
                "resolved": 5,
                "failed": 5,
                "build": 8,
                "percentage": 50.0,
                "date": "2025-01-11",
                "model": "gpt-4-turbo",
                "category": "test-generation",
                "agent_name": "copilot",
                "average_duration": 110.0,
                "average_prompt_tokens": 4500.0,
                "average_completion_tokens": 1200.0,
                "average_llm_duration": 75.0,
                "github_run_id": "run_002",
                "experiment": {
                    "mcp_servers": None,
                    "custom_instructions": False,
                    "custom_agent": None,
                },
                "instance_results": testgen_instance_results,
            },
        ],
        "aggregate": [
            {
                "model": "gpt-4-turbo",
                "agent_name": "copilot",
                "category": "test-generation",
                "experiment": None,
                "total": 10,
                "num_runs": 1,
                "average_duration": 110.0,
                "pass_hat_1": 0.5,
                "pass_hat_3": None,
                "pass_hat_5": None,
            },
        ],
    }

    with open(bugfix_leaderboard_path, "w") as f:
        json.dump(bugfix_data, f, indent=2)

    with open(testgen_leaderboard_path, "w") as f:
        json.dump(testgen_data, f, indent=2)

    # Create a new summary to update (updated copilot + gpt-4o + server1, server2)
    new_summary_instance_results = {f"test__inst_{i}": (i < 8) for i in range(10)}  # 8 resolved

    new_summary = {
        "total": 10,
        "resolved": 8,  # Improved from 6 to 8
        "failed": 2,
        "build": 10,  # Improved from 9 to 10
        "percentage": 80.0,
        "date": "2025-01-15",
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 130.0,
        "average_prompt_tokens": 5200.0,
        "average_completion_tokens": 1600.0,
        "average_llm_duration": 90.0,
        "github_run_id": "run_004",
        "experiment": {
            "mcp_servers": ["server1", "server2"],
            "custom_instructions": True,
            "custom_agent": None,
        },
        "instance_results": new_summary_instance_results,
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
            "--n",
            "1",
        ],
    )

    assert result.exit_code == 0, f"Command failed:\nstdout: {result.stdout}\nstderr: {result.stderr}\nexception: {result.exception}"

    # Verify bug-fix leaderboard still has 2 aggregates (not 3)
    with open(bugfix_leaderboard_path) as f:
        updated_leaderboard = json.load(f)

    assert len(updated_leaderboard["aggregate"]) == 2, "Should still have 2 aggregates (replaced, not added)"

    # Find the updated entry and verify it matches
    updated_agg = None
    for agg in updated_leaderboard["aggregate"]:
        exp = agg.get("experiment") or {}
        if agg["agent_name"] == "copilot" and agg["model"] == "gpt-4o" and exp.get("mcp_servers") == ["server1", "server2"] and exp.get("custom_instructions") is True:
            updated_agg = agg
            break

    assert updated_agg is not None, "Should find the updated copilot + gpt-4o + server1, server2 aggregate"
    # Find the corresponding run
    latest_run = next(r for r in updated_leaderboard["runs"] if r["github_run_id"] == "run_004")
    assert latest_run["resolved"] == 8, "Should have updated resolved count"
    assert latest_run["build"] == 10, "Should have updated build count"
    assert latest_run["average_prompt_tokens"] == 5200.0, "Should have updated average_prompt_tokens"


@pytest.mark.integration
def test_result_update_adds_new_entry(sample_leaderboard_and_summary):
    leaderboard_dir, _ = sample_leaderboard_and_summary
    summary_path = leaderboard_dir.parent / "new_agent_summary.json"

    # Create a new summary for a different agent
    new_agent_instance_results = {f"test__inst_{i}": (i < 9) for i in range(10)}  # 9 resolved

    new_summary = {
        "total": 10,
        "resolved": 9,
        "failed": 1,
        "build": 10,
        "percentage": 90.0,
        "date": "2025-01-16",
        "model": "gpt-4o",
        "category": "test-generation",
        "agent_name": "new-agent",
        "average_duration": 100.0,
        "average_prompt_tokens": 4800.0,
        "average_completion_tokens": 1400.0,
        "average_llm_duration": 70.0,
        "github_run_id": "run_005",
        "experiment": {
            "mcp_servers": None,
            "custom_instructions": False,
            "custom_agent": None,
        },
        "instance_results": new_agent_instance_results,
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
            "--n",
            "1",
        ],
    )

    assert result.exit_code == 0

    # Verify leaderboard now has 2 aggregates in test-generation
    with open(leaderboard_dir / "test-generation.json") as f:
        updated_leaderboard = json.load(f)

    assert len(updated_leaderboard["aggregate"]) == 2, "Should now have 2 aggregates (added new in test-generation)"

    # Find the new entry
    new_agg = None
    for agg in updated_leaderboard["aggregate"]:
        if agg["agent_name"] == "new-agent" and agg["model"] == "gpt-4o":
            new_agg = agg
            break

    assert new_agg is not None, "Should find the new aggregate for new-agent"
    new_run = next(r for r in updated_leaderboard["runs"] if r["agent_name"] == "new-agent")
    assert new_run["resolved"] == 9, "Should have correct resolved count"


@pytest.mark.integration
def test_result_update_distinguishes_by_mcp_servers(sample_leaderboard_and_summary):
    leaderboard_dir, _ = sample_leaderboard_and_summary
    summary_path = leaderboard_dir.parent / "copilot_different_mcp_summary.json"

    # Create a new summary for copilot + gpt-4o but WITHOUT mcp_servers (different from existing)
    diff_mcp_instance_results = {f"test__inst_{i}": (i < 7) for i in range(10)}  # 7 resolved

    new_summary = {
        "total": 10,
        "resolved": 7,
        "failed": 3,
        "build": 9,
        "percentage": 70.0,
        "date": "2025-01-17",
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 115.0,
        "average_prompt_tokens": 4900.0,
        "average_completion_tokens": 1350.0,
        "average_llm_duration": 78.0,
        "github_run_id": "run_006",
        "experiment": {
            "mcp_servers": None,  # Different from existing ["server1", "server2"]
            "custom_instructions": False,  # Different from existing True
            "custom_agent": None,
        },
        "instance_results": diff_mcp_instance_results,
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
            "--n",
            "1",
        ],
    )

    assert result.exit_code == 0

    # Verify bug-fix leaderboard now has 3 aggregates (not replaced because mcp_servers differ)
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"
    with open(bugfix_leaderboard_path) as f:
        updated_leaderboard = json.load(f)

    assert len(updated_leaderboard["aggregate"]) == 3, "Should have 3 aggregates in bug-fix (added new because mcp_servers differ)"

    # Verify both copilot + gpt-4o aggregates exist
    copilot_gpt4o_aggs = [a for a in updated_leaderboard["aggregate"] if a["agent_name"] == "copilot" and a["model"] == "gpt-4o"]

    assert len(copilot_gpt4o_aggs) == 2, "Should have 2 different copilot + gpt-4o aggregates"

    # Find each by experiment.mcp_servers
    with_servers = next((a for a in copilot_gpt4o_aggs if (a.get("experiment") or {}).get("mcp_servers") == ["server1", "server2"]), None)
    without_servers = next((a for a in copilot_gpt4o_aggs if (a.get("experiment") or {}).get("mcp_servers") is None), None)

    assert with_servers is not None and without_servers is not None
    assert with_servers["pass_hat_1"] == 0.6, "Original aggregate should be unchanged"
    assert without_servers["pass_hat_1"] == 0.7, "New aggregate should have new values"


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


@pytest.mark.integration
def test_result_update_stores_multiple_results_with_default_n(sample_leaderboard_and_summary):
    leaderboard_dir, summary_path = sample_leaderboard_and_summary
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"

    # Default n=5 - should add as new entry (even though combination exists)
    # because n>1 means we keep multiple results
    multi_results_instance = {f"test__inst_{i}": (i < 8) for i in range(10)}  # 8 resolved

    new_summary = {
        "total": 10,
        "resolved": 8,
        "failed": 2,
        "build": 10,
        "percentage": 80.0,
        "date": "2025-01-15",
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 130.0,
        "average_prompt_tokens": 5200.0,
        "average_completion_tokens": 1600.0,
        "average_llm_duration": 90.0,
        "github_run_id": "run_new_1",
        "experiment": {
            "mcp_servers": ["server1", "server2"],
            "custom_instructions": True,
            "custom_agent": None,
        },
        "instance_results": multi_results_instance,
    }

    with open(summary_path, "w") as f:
        json.dump(new_summary, f, indent=2)

    result = runner.invoke(
        app,
        ["result", "update", str(summary_path), "--leaderboard-dir", str(leaderboard_dir)],
    )

    assert result.exit_code == 0

    with open(bugfix_leaderboard_path) as f:
        updated_leaderboard = json.load(f)

    # Should still have 2 aggregates (the new result is added to an existing combination's runs)
    assert len(updated_leaderboard["aggregate"]) == 2

    # Verify we have 2 runs for copilot + gpt-4o + server1,server2 (original + new)
    copilot_runs = [r for r in updated_leaderboard["runs"] if r["agent_name"] == "copilot" and r["model"] == "gpt-4o" and (r.get("experiment") or {}).get("mcp_servers") == ["server1", "server2"]]
    assert len(copilot_runs) == 2  # Original + new run


@pytest.mark.integration
def test_result_update_replaces_oldest_when_exceeding_n(sample_leaderboard_and_summary):
    leaderboard_dir, _ = sample_leaderboard_and_summary
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"

    # First, add 4 more results to have 5 total for copilot + gpt-4o + servers combination (default n=5)
    oldest_instance_results = {f"test__inst_{i}": (i < 7) for i in range(10)}  # 7 resolved

    base_summary = {
        "total": 10,
        "resolved": 7,
        "failed": 3,
        "build": 9,
        "percentage": 70.0,
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 120.0,
        "average_prompt_tokens": 5000.0,
        "average_completion_tokens": 1500.0,
        "average_llm_duration": 85.0,
        "experiment": {
            "mcp_servers": ["server1", "server2"],
            "custom_instructions": True,
            "custom_agent": None,
        },
        "instance_results": oldest_instance_results,
    }

    summary_path = leaderboard_dir.parent / "test_summary.json"

    # Add results to fill up to n=5 (original is from 2025-01-10)
    for _, (day, run_id) in enumerate([("2025-01-16", "run_second"), ("2025-01-17", "run_third"), ("2025-01-18", "run_fourth"), ("2025-01-19", "run_fifth")]):
        summary = {**base_summary, "date": day, "github_run_id": run_id}
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        runner.invoke(app, ["result", "update", str(summary_path), "--leaderboard-dir", str(leaderboard_dir)])

    # Now we should have 5 runs for this combination
    with open(bugfix_leaderboard_path) as f:
        leaderboard = json.load(f)

    copilot_runs = [r for r in leaderboard["runs"] if r["agent_name"] == "copilot" and r["model"] == "gpt-4o" and (r.get("experiment") or {}).get("mcp_servers") == ["server1", "server2"]]
    assert len(copilot_runs) == 5

    # Now add a 6th result - should replace oldest (2025-01-10)
    newest_instance_results = {f"test__inst_{i}": (i < 9) for i in range(10)}  # 9 resolved
    summary_new = {**base_summary, "date": "2025-01-20", "github_run_id": "run_sixth", "resolved": 9, "instance_results": newest_instance_results}
    with open(summary_path, "w") as f:
        json.dump(summary_new, f, indent=2)

    result = runner.invoke(app, ["result", "update", str(summary_path), "--leaderboard-dir", str(leaderboard_dir)])
    assert result.exit_code == 0

    with open(bugfix_leaderboard_path) as f:
        final_leaderboard = json.load(f)

    # Should still have 5 runs for this combination
    final_copilot_runs = [r for r in final_leaderboard["runs"] if r["agent_name"] == "copilot" and r["model"] == "gpt-4o" and (r.get("experiment") or {}).get("mcp_servers") == ["server1", "server2"]]
    assert len(final_copilot_runs) == 5

    # The oldest (2025-01-10) should be gone, replaced by 2025-01-20
    dates = sorted(r["date"] for r in final_copilot_runs)
    assert dates == ["2025-01-16", "2025-01-17", "2025-01-18", "2025-01-19", "2025-01-20"]

    # Verify the newest entry has the correct resolved count
    newest = next(r for r in final_copilot_runs if r["date"] == "2025-01-20")
    assert newest["resolved"] == 9
    assert newest["github_run_id"] == "run_sixth"


@pytest.mark.integration
def test_result_refresh_recalculates_aggregates(sample_leaderboard_and_summary):
    leaderboard_dir, _ = sample_leaderboard_and_summary
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"

    # Corrupt the aggregates to verify refresh recalculates them
    with open(bugfix_leaderboard_path) as f:
        leaderboard = json.load(f)

    for agg in leaderboard["aggregate"]:
        agg["pass_hat_1"] = 999.0  # Invalid value

    with open(bugfix_leaderboard_path, "w") as f:
        json.dump(leaderboard, f, indent=2)

    # Run refresh command
    result = runner.invoke(app, ["result", "refresh", "--leaderboard-dir", str(leaderboard_dir)])
    assert result.exit_code == 0

    # Verify aggregates were recalculated correctly
    with open(bugfix_leaderboard_path) as f:
        refreshed = json.load(f)

    # Should have 2 aggregates (copilot with servers, mini without)
    assert len(refreshed["aggregate"]) == 2

    # All pass_hat_1 values should be recalculated (not 999)
    for agg in refreshed["aggregate"]:
        assert agg["pass_hat_1"] != 999.0
        assert agg["pass_hat_1"] > 0


@pytest.mark.integration
def test_result_refresh_handles_empty_leaderboard(tmp_path):
    # Create an empty leaderboard file
    empty_leaderboard = tmp_path / "bug-fix.json"
    empty_leaderboard.write_text("[]")

    result = runner.invoke(app, ["result", "refresh", "--leaderboard-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No runs found" in result.output


@pytest.mark.integration
def test_result_refresh_handles_legacy_runs_without_instance_results(tmp_path):
    """Test that refresh handles legacy runs that don't have instance_results."""
    leaderboard_path = tmp_path / "bug-fix.json"

    legacy_data = {
        "runs": [
            {
                "total": 10,
                "resolved": 6,
                "failed": 4,
                "build": 9,
                "percentage": 60.0,
                "date": "2025-01-10",
                "model": "gpt-4o",
                "category": "bug-fix",
                "agent_name": "legacy-agent",
                "average_duration": 100.0,
                "average_prompt_tokens": 4000.0,
                "average_completion_tokens": 1200.0,
                "average_llm_duration": 70.0,
                "github_run_id": "run_legacy",
                "experiment": None,
                "instance_results": None,  # Legacy: no instance_results
            },
        ],
        "aggregate": [
            {
                "model": "gpt-4o",
                "agent_name": "legacy-agent",
                "category": "bug-fix",
                "experiment": None,
                "total": 10,
                "num_runs": 1,
                "average_duration": 100.0,
                "pass_hat_1": 0.0,  # Incorrectly set to 0
                "pass_hat_3": None,
                "pass_hat_5": None,
            },
        ],
    }

    with open(leaderboard_path, "w") as f:
        json.dump(legacy_data, f, indent=2)

    result = runner.invoke(app, ["result", "refresh", "--leaderboard-dir", str(tmp_path)])
    assert result.exit_code == 0

    with open(leaderboard_path) as f:
        refreshed = json.load(f)

    # Should fall back to pass rate (resolved/total) from run
    assert refreshed["aggregate"][0]["pass_hat_1"] == 0.6
