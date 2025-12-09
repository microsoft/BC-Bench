import subprocess
from unittest.mock import MagicMock, patch

import pytest

from bcbench.agent.copilot import get_copilot_version


def test_get_copilot_version_parses_version_from_stdout():
    mock_result = MagicMock()
    mock_result.stdout = "copilot 0.0.367\n"
    mock_result.stderr = ""

    with patch("bcbench.agent.copilot.agent.shutil.which", return_value="/usr/bin/copilot"), patch("bcbench.agent.copilot.agent.subprocess.run", return_value=mock_result):
        version = get_copilot_version()

    assert version == "0.0.367"


def test_get_copilot_version_parses_version_from_stderr():
    mock_result = MagicMock()
    mock_result.stdout = ""
    mock_result.stderr = "copilot 1.2.345\n"

    with patch("bcbench.agent.copilot.agent.shutil.which", return_value="/usr/bin/copilot"), patch("bcbench.agent.copilot.agent.subprocess.run", return_value=mock_result):
        version = get_copilot_version()

    assert version == "1.2.345"


def test_get_copilot_version_handles_version_only_output():
    mock_result = MagicMock()
    mock_result.stdout = "0.0.400"
    mock_result.stderr = ""

    with patch("bcbench.agent.copilot.agent.shutil.which", return_value="/usr/bin/copilot"), patch("bcbench.agent.copilot.agent.subprocess.run", return_value=mock_result):
        version = get_copilot_version()

    assert version == "0.0.400"


def test_get_copilot_version_handles_verbose_output():
    mock_result = MagicMock()
    mock_result.stdout = "GitHub Copilot CLI version 2.1.0 (build abc123)\n"
    mock_result.stderr = ""

    with patch("bcbench.agent.copilot.agent.shutil.which", return_value="/usr/bin/copilot"), patch("bcbench.agent.copilot.agent.subprocess.run", return_value=mock_result):
        version = get_copilot_version()

    assert version == "2.1.0"


def test_get_copilot_version_handles_two_component_version():
    mock_result = MagicMock()
    mock_result.stdout = "copilot 1.2\n"
    mock_result.stderr = ""

    with patch("bcbench.agent.copilot.agent.shutil.which", return_value="/usr/bin/copilot"), patch("bcbench.agent.copilot.agent.subprocess.run", return_value=mock_result):
        version = get_copilot_version()

    assert version == "1.2"


def test_get_copilot_version_handles_four_component_version():
    mock_result = MagicMock()
    mock_result.stdout = "copilot 1.2.3.4\n"
    mock_result.stderr = ""

    with patch("bcbench.agent.copilot.agent.shutil.which", return_value="/usr/bin/copilot"), patch("bcbench.agent.copilot.agent.subprocess.run", return_value=mock_result):
        version = get_copilot_version()

    assert version == "1.2.3.4"


def test_get_copilot_version_raises_when_cli_not_found():
    with patch("bcbench.agent.copilot.agent.shutil.which", return_value=None), pytest.raises(FileNotFoundError, match="Copilot CLI not found in PATH"):
        get_copilot_version()


def test_get_copilot_version_raises_on_invalid_output():
    mock_result = MagicMock()
    mock_result.stdout = "some invalid output without version"
    mock_result.stderr = ""

    with (
        patch("bcbench.agent.copilot.agent.shutil.which", return_value="/usr/bin/copilot"),
        patch("bcbench.agent.copilot.agent.subprocess.run", return_value=mock_result),
        pytest.raises(ValueError, match="Could not parse version"),
    ):
        get_copilot_version()


def test_get_copilot_version_raises_on_timeout():
    with (
        patch("bcbench.agent.copilot.agent.shutil.which", return_value="/usr/bin/copilot"),
        patch(
            "bcbench.agent.copilot.agent.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="copilot --version", timeout=10),
        ),
        pytest.raises(subprocess.TimeoutExpired),
    ):
        get_copilot_version()


def test_get_copilot_version_raises_on_os_error():
    with (
        patch("bcbench.agent.copilot.agent.shutil.which", return_value="/usr/bin/copilot"),
        patch("bcbench.agent.copilot.agent.subprocess.run", side_effect=OSError("Command failed")),
        pytest.raises(OSError, match="Command failed"),
    ):
        get_copilot_version()


def test_get_copilot_version_prefers_copilot_cmd_on_windows():
    mock_result = MagicMock()
    mock_result.stdout = "copilot 0.0.367\n"
    mock_result.stderr = ""

    def mock_which(cmd):
        if cmd == "copilot.cmd":
            return "C:\\copilot.cmd"
        return None

    with patch("bcbench.agent.copilot.agent.shutil.which", side_effect=mock_which), patch("bcbench.agent.copilot.agent.subprocess.run", return_value=mock_result) as mock_run:
        version = get_copilot_version()

    assert version == "0.0.367"
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == ["C:\\copilot.cmd", "--version"]
