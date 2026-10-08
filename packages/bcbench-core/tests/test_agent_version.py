import subprocess
from unittest.mock import patch

import pytest

from bcbench_core.agent.copilot import get_copilot_version
from bcbench_core.agent.version import get_cli_version
from bcbench_core.exceptions import AgentError


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("GitHub Copilot CLI 1.0.82\nCommit: abc\n", "1.0.82"),
        ("2.1.221 (Claude Code)\n", "2.1.221"),
        ("1.2.3-preview.4+build.5\n", "1.2.3-preview.4+build.5"),
    ],
)
def test_cli_version_parsing(output: str, expected: str) -> None:
    with patch("bcbench_core.agent.version.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=output)) as run:
        assert get_cli_version("agent", "Test Agent") == expected
    assert run.call_args.args[0] == ["agent", "--version"]
    assert run.call_args.kwargs["check"] is True
    assert run.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("output", ["", "unknown", "1.2"])
def test_invalid_cli_version_is_an_error(output: str) -> None:
    with (
        patch("bcbench_core.agent.version.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=output)),
        pytest.raises(AgentError, match="Unrecognized Test Agent version output"),
    ):
        get_cli_version("agent", "Test Agent")


def test_missing_cli_is_an_error() -> None:
    with pytest.raises(AgentError, match="Test Agent not found"):
        get_cli_version(None, "Test Agent")


@pytest.mark.parametrize("error", [OSError("unavailable"), subprocess.CalledProcessError(1, ["agent"]), subprocess.TimeoutExpired(["agent"], 30)])
def test_cli_version_command_failure_is_an_error(error: Exception) -> None:
    with (
        patch("bcbench_core.agent.version.subprocess.run", side_effect=error),
        pytest.raises(AgentError, match="Could not determine Test Agent version"),
    ):
        get_cli_version("agent", "Test Agent")


def test_copilot_version_uses_the_evaluation_executable_resolver() -> None:
    with (
        patch("bcbench_core.agent.copilot.agent._find_copilot", return_value="chosen-copilot.exe"),
        patch("bcbench_core.agent.copilot.agent.get_cli_version", return_value="1.2.3") as version,
    ):
        assert get_copilot_version() == "1.2.3"
    version.assert_called_once_with("chosen-copilot.exe", "GitHub Copilot CLI")
