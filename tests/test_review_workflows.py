import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"
ACTIONS = Path(__file__).parents[1] / ".github" / "actions"
AGENT_CONFIG = Path(__file__).parents[1] / "src" / "bcbench" / "agent" / "shared" / "config.yaml"
DEFAULT_ENGINE_SHA = "75d67cd7c18b9ad98a1c3cbf6d173e5bdba53b9c"
PWSH = shutil.which("pwsh")


def _workflow(name: str) -> str:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert yaml.safe_load(text)
    return text


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
    workflow_data = yaml.safe_load(workflow)
    inputs = workflow_data[True]["workflow_dispatch"]["inputs"]
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
    assert 'agent: "BC PR Review"' in workflow
    assert '"mai-code-1.1-flash"' in workflow
    assert "mai-code-1-flash-picker" not in workflow
    assert "claude-" not in workflow
    assert "gemini-" not in workflow
    assert inputs["model"]["default"] == "gpt-5.6-sol"
    assert inputs["model"]["options"] == [
        "gpt-5.4",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.3-codex",
        "mai-code-1.1-flash",
    ]
    assert inputs["leaf-model"]["default"] == "gpt-5.6-luna"
    assert inputs["leaf-model"]["options"] == ["gpt-5.4", "gpt-5.6-luna", "mai-code-1.1-flash"]
    assert 'leaf-execution:\n        description: "Deterministic leaf scheduling mode"\n        required: false\n        default: "serial"' in workflow
    assert 'max-leaf-concurrency:\n        description: "Maximum simultaneous leaves in parallel mode"' in workflow
    assert 'COPILOT_REVIEW_CLI_VERSION: "1.0.83"' in workflow
    assert "COPILOT_REVIEW_LEAF_MODEL: ${{ inputs.leaf-model }}" in workflow
    assert "COPILOT_REVIEW_LEAF_EXECUTION: ${{ inputs.leaf-execution }}" in workflow
    assert "COPILOT_REVIEW_MAX_LEAF_CONCURRENCY: ${{ inputs.max-leaf-concurrency }}" in workflow
    assert workflow_data["concurrency"]["group"] == "pr-review-evaluation-${{ inputs.modified-only && 'modified' || inputs.test-run && 'test' || 'full' }}"
    assert "repetition-id" not in workflow
    for input_name in (
        "model:",
        "leaf-model:",
        "leaf-execution:",
        "max-leaf-concurrency:",
        "engine-sha:",
        "test-run:",
        "modified-only:",
        "repeat:",
        "entries:",
        "git-ref:",
    ):
        assert input_name in workflow


def test_pr_review_focused_selection_and_diagnostics_are_wired() -> None:
    workflow = yaml.safe_load(_workflow("pr-review-evaluation.yml"))
    job = workflow["jobs"]["evaluate-with-pr-review"]
    assert job["strategy"]["matrix"]["entry"] == "${{ fromJson(inputs.entries != '' && inputs.entries || needs.get-entries.outputs.entries) }}"
    assert job["strategy"]["max-parallel"] == 64
    run = next(step for step in job["steps"] if step["name"].startswith("Run BC PR Review"))
    assert run["env"]["MINIMUM_SEVERITY"] == "Medium"
    assert run["env"]["AGENT_MINIMUM_SEVERITY"] == "Medium"
    assert "Tee-Object -FilePath evaluation.log" in run["run"]
    assert "exit $LASTEXITCODE" in run["run"]
    collect = next(step for step in job["steps"] if step["name"] == "Collect experiment diagnostics")
    upload = next(step for step in job["steps"] if step["name"] == "Upload experiment diagnostics")
    assert collect["if"] == upload["if"] == "always()"
    assert "Where-Object { $_.Name -in $allowed }" in collect["run"]
    assert "judge_results.json" in collect["run"]
    assert upload["with"]["path"] == "diagnostics-${{ matrix.entry }}.tar.gz"
    assert upload["with"]["if-no-files-found"] == "error"


@pytest.mark.skipif(PWSH is None or shutil.which("tar") is None, reason="PowerShell and tar are required to test diagnostics")
def test_pr_review_diagnostics_archive_only_allowed_outputs(tmp_path: Path) -> None:
    assert PWSH is not None
    workflow = yaml.safe_load(_workflow("pr-review-evaluation.yml"))
    collect = next(step for step in workflow["jobs"]["evaluate-with-pr-review"]["steps"] if step["name"] == "Collect experiment diagnostics")
    results = tmp_path / "evaluation_results"
    leaf = results / "run" / "leaf-results" / "performance"
    leaf.mkdir(parents=True)
    (leaf / "_review-report.json").write_text("{}", encoding="utf-8")
    (leaf / "unrelated.json").write_text("not an output", encoding="utf-8")
    (results / "run" / "_run-manifest.json").write_text("{}", encoding="utf-8")
    target_repo = tmp_path / "target"
    target_repo.mkdir()
    (target_repo / "review.json").write_text("[]", encoding="utf-8")
    (target_repo / "judge_results.json").write_text("[]", encoding="utf-8")
    (target_repo / ".env").write_text("do not upload", encoding="utf-8")
    (tmp_path / "evaluation.log").write_text("redacted log", encoding="utf-8")

    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", collect["run"]],
        cwd=tmp_path,
        env={**os.environ, "EVALUATION_RESULTS_DIR": str(results), "TARGET_REPO": str(target_repo), "ENTRY_ID": "synthetic__performance-009"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    with tarfile.open(tmp_path / "diagnostics-synthetic__performance-009.tar.gz") as archive:
        names = {member.name.removeprefix("./") for member in archive.getmembers() if member.isfile()}
    assert names == {
        "run/leaf-results/performance/_review-report.json",
        "run/_run-manifest.json",
        "review.json",
        "judge_results.json",
        "evaluation.log",
    }


def test_pr_review_workflow_passes_optional_engine_sha_to_harness_action() -> None:
    workflow = yaml.safe_load(_workflow("pr-review-evaluation.yml"))
    engine_input = workflow[True]["workflow_dispatch"]["inputs"]["engine-sha"]
    install = next(step for step in workflow["jobs"]["evaluate-with-pr-review"]["steps"] if step.get("id") == "install-harnesses")

    assert engine_input["required"] is False
    assert engine_input["default"] == ""
    assert engine_input["type"] == "string"
    assert install["with"]["engine-sha"] == "${{ inputs.engine-sha }}"
    assert DEFAULT_ENGINE_SHA not in _workflow("pr-review-evaluation.yml")


def test_engine_sha_override_is_never_published_as_a_benchmark_result() -> None:
    """An override runs a revision other than the reviewed default pin, so it must stay off the dashboards."""
    workflow = yaml.safe_load(_workflow("pr-review-evaluation.yml"))
    summarize = workflow["jobs"]["summarize-results"]["with"]

    assert summarize["mock"] == "${{ inputs.test-run || inputs.modified-only || inputs.engine-sha != '' || inputs.entries != '' }}"
    # Repeats stay available so an override can be measured over several runs.
    assert "inputs.engine-sha" not in workflow["jobs"]["requeue"]["if"]


@pytest.mark.parametrize("engine_sha", ["", "a" * 40, "A" * 40, "'\"$(echo injected)"])
def test_pr_review_requeue_preserves_engine_sha(engine_sha: str) -> None:
    workflow = yaml.safe_load(_workflow("pr-review-evaluation.yml"))
    payload = workflow["jobs"]["requeue"]["with"]["workflow-inputs"]
    engine_expression = "${{ toJSON(inputs.engine-sha) }}"
    entries_expression = "${{ toJSON(inputs.entries) }}"

    assert engine_expression in payload
    parsed = json.loads(payload.replace(engine_expression, json.dumps(engine_sha)).replace(entries_expression, json.dumps("")))
    assert parsed["engine-sha"] == engine_sha


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

    assert "@github/copilot@1.0.83" in action


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
