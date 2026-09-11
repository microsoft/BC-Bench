import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.claude import get_claude_version
from bcbench.agent.copilot import get_copilot_version
from bcbench.agent.pr_review import get_pr_review_version
from bcbench.agent.shared.version import get_cli_version
from bcbench.exceptions import AgentError
from bcbench.operations import commit_changes, init_repo


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("GitHub Copilot CLI 1.0.82\nCommit: abc\n", "1.0.82"),
        ("2.1.221 (Claude Code)\n", "2.1.221"),
        ("1.2.3-preview.4+build.5\n", "1.2.3-preview.4+build.5"),
    ],
)
def test_cli_version_parsing(output: str, expected: str) -> None:
    with patch("bcbench.agent.shared.version.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=output)) as run:
        assert get_cli_version("agent", "Test Agent") == expected
    assert run.call_args.args[0] == ["agent", "--version"]
    assert run.call_args.kwargs["check"] is True
    assert run.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("output", ["", "unknown", "1.2"])
def test_invalid_cli_version_is_an_error(output: str) -> None:
    with (
        patch("bcbench.agent.shared.version.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=output)),
        pytest.raises(AgentError, match="Unrecognized Test Agent version output"),
    ):
        get_cli_version("agent", "Test Agent")


def test_missing_cli_is_an_error() -> None:
    with pytest.raises(AgentError, match="Test Agent not found"):
        get_cli_version(None, "Test Agent")


@pytest.mark.parametrize("error", [OSError("unavailable"), subprocess.CalledProcessError(1, ["agent"]), subprocess.TimeoutExpired(["agent"], 30)])
def test_cli_version_command_failure_is_an_error(error: Exception) -> None:
    with (
        patch("bcbench.agent.shared.version.subprocess.run", side_effect=error),
        pytest.raises(AgentError, match="Could not determine Test Agent version"),
    ):
        get_cli_version("agent", "Test Agent")


def test_copilot_version_uses_the_evaluation_executable_resolver() -> None:
    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="chosen-copilot.exe"),
        patch("bcbench.agent.copilot.cli.get_cli_version", return_value="1.2.3") as version,
    ):
        assert get_copilot_version() == "1.2.3"
    version.assert_called_once_with("chosen-copilot.exe", "GitHub Copilot CLI")


def test_claude_version_uses_the_evaluation_executable_resolver() -> None:
    with (
        patch("bcbench.agent.claude.agent.shutil.which", return_value="chosen-claude") as which,
        patch("bcbench.agent.claude.agent.get_cli_version", return_value="1.2.3") as version,
    ):
        assert get_claude_version() == "1.2.3"
    which.assert_called_once_with("claude")
    version.assert_called_once_with("chosen-claude", "Claude Code")


def _write_engine(root: Path) -> None:
    script = root / "agents" / "ALReviewAgent" / "scripts" / "Invoke-CopilotPRReview.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# Test engine\n", encoding="utf-8")


@pytest.fixture
def engine_root(tmp_path: Path) -> Path:
    _write_engine(tmp_path)
    init_repo(tmp_path)
    commit_changes(tmp_path, "Test engine", no_verify=True)
    return tmp_path


def test_engine_version_is_the_full_checked_out_commit(engine_root: Path) -> None:
    expected = subprocess.run(["git", "-C", str(engine_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert get_pr_review_version(engine_root) == expected
    assert len(expected) == 40


@pytest.mark.parametrize("staged", [False, True])
def test_dirty_engine_cannot_be_reported_as_a_commit(engine_root: Path, staged: bool) -> None:
    (engine_root / "new-rule.md").write_text("New behavior", encoding="utf-8")
    if staged:
        subprocess.run(["git", "-C", str(engine_root), "add", "."], check=True)

    with pytest.raises(AgentError, match="clean engine checkout"):
        get_pr_review_version(engine_root)


def test_engine_path_must_be_the_checkout_root(engine_root: Path) -> None:
    nested = engine_root / "nested"
    _write_engine(nested)
    with pytest.raises(AgentError, match="root of a Git checkout"):
        get_pr_review_version(nested)


def test_engine_must_be_a_git_checkout(tmp_path: Path) -> None:
    _write_engine(tmp_path)
    with pytest.raises(AgentError, match="Could not determine PR Review engine version"):
        get_pr_review_version(tmp_path)


def test_engine_path_is_required() -> None:
    with pytest.raises(AgentError, match="Engine root not configured"):
        get_pr_review_version(None)
