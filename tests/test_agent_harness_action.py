import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ACTIONS = Path(__file__).parents[1] / ".github" / "actions"
DEFAULT_ENGINE_SHA = "ecf8e31759d6ddd6d78e3a0b7836b40134368009"
PWSH = shutil.which("pwsh")


def test_agent_harness_action_pins_published_copilot_version() -> None:
    action = (ACTIONS / "install-agent-harnesses" / "action.yml").read_text(encoding="utf-8")

    assert "@github/copilot@1.0.82" in action


def test_agent_harness_action_pins_and_exports_bc_alagents() -> None:
    action = (ACTIONS / "install-agent-harnesses" / "action.yml").read_text(encoding="utf-8")
    config = yaml.safe_load(action)
    validation = next(step for step in config["runs"]["steps"] if step.get("id") == "engine-sha")
    checkout = next(step for step in config["runs"]["steps"] if step.get("uses", "").startswith("actions/checkout@"))

    assert "repository: microsoft/BC-ALAgents" in action
    assert "bc-alagents-path:" in action
    assert config["inputs"]["engine-sha"]["required"] is False
    assert config["inputs"]["engine-sha"]["default"] == ""
    assert validation["env"]["ENGINE_SHA"] == "${{ inputs.engine-sha || '" + DEFAULT_ENGINE_SHA + "' }}"
    assert "${{" not in validation["run"]
    assert action.count(DEFAULT_ENGINE_SHA) == 1
    assert config["runs"]["steps"].index(validation) < config["runs"]["steps"].index(checkout)
    assert checkout["with"]["ref"] == "${{ steps.engine-sha.outputs.sha }}"
    assert checkout["with"]["persist-credentials"] is False
    assert set(config["outputs"]) == {"bc-alagents-path"}


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test the composite action script")
@pytest.mark.parametrize(
    ("engine_sha", "valid"),
    [
        ("", True),
        ("a" * 40, True),
        ("ABCDEF0123" * 4, True),
        ("main", False),
        ("v1.39.6", False),
        ("ecf8e31", False),
        ("a" * 39, False),
        ("a" * 41, False),
        ("g" * 40, False),
        (" " * 40, False),
        ("a" * 40 + "\n", False),
        ("a" * 40 + "\r\n", False),
        ("a" * 40 + "; Write-Output injected", False),
        ("$(Write-Output injected)", False),
    ],
)
def test_agent_harness_action_validates_engine_sha(engine_sha: str, valid: bool, tmp_path: Path) -> None:
    assert PWSH is not None
    action = yaml.safe_load((ACTIONS / "install-agent-harnesses" / "action.yml").read_text(encoding="utf-8"))
    validation = next(step for step in action["runs"]["steps"] if step.get("id") == "engine-sha")
    output = tmp_path / "github-output"
    resolved_sha = engine_sha or DEFAULT_ENGINE_SHA

    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", validation["run"]],
        env={**os.environ, "ENGINE_SHA": resolved_sha, "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        check=False,
    )

    if valid:
        assert result.returncode == 0, result.stderr
        assert output.read_text(encoding="utf-8") == f"sha={resolved_sha}\n"
    else:
        assert result.returncode != 0
        assert "engine-sha must be a full 40-character hexadecimal commit SHA." in result.stderr
        assert not output.exists()
