import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"
ACTIONS = Path(__file__).parents[1] / ".github" / "actions"
AGENT_CONFIG = Path(__file__).parents[1] / "src" / "bcbench" / "agent" / "shared" / "config.yaml"
DEFAULT_ENGINE_SHA = "17f5761d95ee08d47dd1a68571e84b1c440883c5"
PWSH = shutil.which("pwsh")


def _workflow(name: str) -> str:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert yaml.safe_load(text)
    return text


def test_ci_mock_artifact_name_matches_code_review_summary_filter() -> None:
    ci = yaml.safe_load(_workflow("CI.yml"))
    summary = yaml.safe_load(_workflow("summarize-results.yml"))
    upload = next(step for step in ci["jobs"]["mock-evaluation"]["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
    download = next(step for step in summary["jobs"]["summarize-results"]["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))

    assert upload["with"]["name"] == "evaluation-results-${{ github.run_id }}-${{ matrix.entry }}"
    assert upload["with"]["path"] == "${{ env.EVALUATION_RESULTS_DIR }}/**/*.jsonl"
    assert download["with"]["pattern"] == "${{ (inputs.dataset != '' || inputs.category == 'code-review') && 'evaluation-results-*' || '*' }}"
    assert download["with"]["merge-multiple"] is True
    assert ci["jobs"]["summarize-results"]["with"]["mock"] is True


def test_copilot_workflow_routes_code_review_through_copilot() -> None:
    workflow = _workflow("copilot-evaluation.yml")

    assert '"code-review"' in workflow
    assert "bcbench evaluate copilot" in workflow
    assert "bcbench evaluate pr-review" not in workflow
    assert "BC_PR_REVIEW_ROOT" not in workflow
    assert 'agent: "GitHub Copilot CLI"' in workflow


def test_claude_workflow_routes_code_review_through_claude() -> None:
    workflow = _workflow("claude-evaluation.yml")

    assert '"code-review"' in workflow
    assert "bcbench evaluate claude" in workflow
    assert 'agent: "Claude Code"' in workflow


def test_pr_review_workflow_is_fixed_to_code_review() -> None:
    workflow = _workflow("pr-review-evaluation.yml")
    config = yaml.safe_load(AGENT_CONFIG.read_text(encoding="utf-8"))

    assert "category: code-review" in workflow
    assert "bcbench evaluate pr-review" in workflow
    assert "Checkout BC-ALAgents review engine" not in workflow
    assert '--engine-path "${{ steps.install-harnesses.outputs.bc-alagents-path }}"' in workflow
    assert config["pr_review"] == {"min_severity": "Medium"}
    assert "BC_PR_REVIEW_ROOT:" not in workflow
    assert "install-agent-harnesses" in workflow
    assert "install-eval-clis" not in workflow
    assert "copilot-requests: write" in workflow
    assert "'BC PR Review'" in workflow
    assert '"mai-code-1.1-flash"' in workflow
    assert "mai-code-1-flash-picker" not in workflow
    assert '"gemini-3.7-flash"' in workflow
    assert "gemini-3.6-flash" not in workflow
    for input_name in ("model:", "engine-sha:", "test-run:", "repeat:", "git-ref:", "modified-only:"):
        assert input_name in workflow


def test_pr_review_workflow_passes_optional_engine_sha_to_harness_action() -> None:
    workflow = yaml.safe_load(_workflow("pr-review-evaluation.yml"))
    engine_input = workflow[True]["workflow_dispatch"]["inputs"]["engine-sha"]
    install = next(step for step in workflow["jobs"]["evaluate-with-pr-review"]["steps"] if step.get("id") == "install-harnesses")

    assert engine_input["required"] is False
    assert engine_input["default"] == ""
    assert engine_input["type"] == "string"
    assert install["with"]["engine-sha"] == "${{ inputs.engine-sha }}"
    assert DEFAULT_ENGINE_SHA not in _workflow("pr-review-evaluation.yml")


def test_experiment_workflow_freezes_root_leaf_cli_and_both_severity_floors() -> None:
    workflow = yaml.safe_load(_workflow("pr-review-evaluation.yml"))
    config = yaml.safe_load(AGENT_CONFIG.read_text(encoding="utf-8"))
    step = next(step for step in workflow["jobs"]["evaluate-with-pr-review"]["steps"] if "bcbench evaluate pr-review" in step.get("run", ""))
    assert workflow[True]["workflow_dispatch"]["inputs"]["model"]["default"] == "gpt-5.6-sol"
    assert step["env"]["COPILOT_REVIEW_CLI_VERSION"] == "1.0.88"
    assert step["env"]["COPILOT_AUTO_UPDATE"] == "false"
    assert step["env"]["COPILOT_REVIEW_LEAF_MODEL"] == "gpt-5.6-luna"
    assert step["env"]["COPILOT_REVIEW_LEAF_EXECUTION"] == "serial"
    assert step["env"]["MINIMUM_SEVERITY"] == config["pr_review"]["min_severity"] == "Medium"
    assert config["judges"]["code-review"]["model"] == "gpt-5.3-codex"


def test_engine_sha_override_is_never_published_as_a_benchmark_result() -> None:
    """An override runs a revision other than the reviewed default pin, so it must stay off the dashboards."""
    workflow = yaml.safe_load(_workflow("pr-review-evaluation.yml"))
    summarize = workflow["jobs"]["summarize-results"]["with"]

    assert summarize["mock"] == "${{ inputs.test-run || inputs.modified-only || inputs.engine-sha != '' || inputs.review-integration == 'none' }}"
    # Repeats stay available so an override can be measured over several runs.
    assert "inputs.engine-sha" not in workflow["jobs"]["requeue"]["if"]


@pytest.mark.parametrize("engine_sha", ["", "a" * 40, "A" * 40, "'\"$(echo injected)"])
def test_pr_review_requeue_preserves_engine_sha(engine_sha: str) -> None:
    workflow = yaml.safe_load(_workflow("pr-review-evaluation.yml"))
    payload = workflow["jobs"]["requeue"]["with"]["workflow-inputs"]
    expression = "${{ toJSON(inputs.engine-sha) }}"

    assert expression in payload
    assert json.loads(payload.replace(expression, json.dumps(engine_sha)))["engine-sha"] == engine_sha


def test_requeue_workflow_reads_inputs_from_environment() -> None:
    workflow = yaml.safe_load(_workflow("requeue-evaluation.yml"))
    requeue = workflow["jobs"]["requeue-if-needed"]["steps"][0]

    assert requeue["env"]["INPUTS_JSON"] == "${{ inputs.workflow-inputs }}"
    assert "${{ inputs.workflow-inputs }}" not in requeue["run"]
    assert """printf '%s' "${INPUTS_JSON}" | jq""" in requeue["run"]
    assert "select(.value != null)" in requeue["run"]
    assert '"${ARGS[@]}"' in requeue["run"]


def test_pr_review_workflow_propagates_modified_only() -> None:
    workflow = _workflow("pr-review-evaluation.yml")

    # Entry selection is delegated to get-entries.yml, which already implements --modified-only.
    assert "modified-only: ${{ inputs.modified-only }}" in workflow


def test_pr_review_workflow_treats_modified_only_as_a_partial_run() -> None:
    """A modified-only run scores a subset, so it must not be recorded as a benchmark result."""
    workflow = _workflow("pr-review-evaluation.yml")

    # Publishing to Braintrust/Kusto and the leaderboard is gated on `mock`.
    assert "inputs.test-run || inputs.modified-only ||" in workflow
    assert "retention-days: ${{ (inputs.test-run || inputs.modified-only) && 1 || 30 }}" in workflow
    # One run verifies the new entries; repeats are for the full corpus after merge.
    assert "!inputs.test-run && !inputs.modified-only" in workflow
    # With requeue disabled, pin-commit must not create a tag nothing would clean up.
    assert "test-run: ${{ inputs.test-run || inputs.modified-only }}" in workflow
    # A requeued run is always a full-corpus run, so the payload must not carry the flag.
    assert "modified-only" not in workflow.split("workflow-inputs:")[1]


def test_agent_harness_action_pins_published_copilot_version() -> None:
    action = (ACTIONS / "install-agent-harnesses" / "action.yml").read_text(encoding="utf-8")

    assert "@github/copilot@1.0.88" in action
    assert "npm install --prefix" in action
    assert "localRequire.resolve" in action
    assert "--no-auto-update --version" in action
    assert "'COPILOT_AUTO_UPDATE=false' >> $env:GITHUB_ENV" in action
    assert "(Split-Path -Parent $native) >> $env:GITHUB_PATH" in action


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test the composite action script")
@pytest.mark.parametrize("failure", [None, "npm", "node", "version", "banner"])
def test_pinned_cli_installation_exports_only_a_verified_native_runtime(tmp_path: Path, failure: str | None) -> None:
    assert PWSH is not None
    action = yaml.safe_load((ACTIONS / "install-agent-harnesses" / "action.yml").read_text(encoding="utf-8"))
    install = next(step for step in action["runs"]["steps"] if step["name"] == "Install GitHub Copilot CLI")
    runtime = tmp_path / "native runtime with spaces"
    runtime.mkdir()
    native = runtime / "copilot.ps1"
    version = "1.0.102-1" if failure == "banner" else "1.0.88"
    native.write_text(
        f"if (($args -join '|') -cne '--no-auto-update|--version') {{ exit 19 }}\n'GitHub Copilot CLI {version}.'\nexit {23 if failure == 'version' else 0}\n",
        encoding="utf-8",
    )
    path_file, env_file = tmp_path / "github-path", tmp_path / "github-env"
    stubs = f"function npm {{ $global:LASTEXITCODE = {23 if failure == 'npm' else 0} }}\nfunction node {{ $global:LASTEXITCODE = {23 if failure == 'node' else 0}; $env:TEST_NATIVE }}\n"
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", stubs + install["run"]],
        env={**os.environ, "RUNNER_TEMP": str(tmp_path), "GITHUB_PATH": str(path_file), "GITHUB_ENV": str(env_file), "TEST_NATIVE": str(native)},
        capture_output=True,
        text=True,
        check=False,
    )
    if failure is None:
        assert result.returncode == 0, result.stderr
        assert path_file.read_text(encoding="utf-8").strip() == str(runtime)
        assert env_file.read_text(encoding="utf-8") == "COPILOT_AUTO_UPDATE=false\n"
    else:
        assert result.returncode != 0
        assert not path_file.exists()
        assert not env_file.exists()


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


def test_agent_workflows_select_al_tool_dotnet_version_for_bc_version() -> None:
    setup_action = (ACTIONS / "setup-bc-container-repo" / "action.yml").read_text(encoding="utf-8")

    assert 'Major -lt 29) { "8.0" } else { "10.0" }' in setup_action
    assert "al_tool_dotnet_version=$alToolDotNetVersion" in setup_action

    for workflow_name in ("claude-evaluation.yml", "copilot-evaluation.yml"):
        workflow = _workflow(workflow_name)
        assert '--framework "net${{ steps.setup-env.outputs.al_tool_dotnet_version }}"' in workflow
