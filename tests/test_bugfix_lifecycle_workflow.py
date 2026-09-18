import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.conftest import create_dataset_entry

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "bugfix-production-evaluation.yml"
ACTION = ROOT / ".github" / "actions" / "setup-bugfix-lifecycle" / "action.yml"
SUMMARY = ROOT / ".github" / "workflows" / "summarize-results.yml"
PWSH = shutil.which("pwsh")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step(steps: list[dict], step_id: str) -> dict:
    return next(step for step in steps if step.get("id") == step_id)


def test_opt_in_dispatch_and_fixed_bugfix_matrix() -> None:
    workflow = _load(WORKFLOW)
    # PyYAML's YAML 1.1 loader treats the unquoted Actions "on" key as True.
    assert set(workflow[True]) == {"workflow_dispatch"}
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"agent", "model", "test-run", "al-mcp", "al-lsp", "bc-mcp", "rehearsal"}
    assert inputs["agent"]["options"] == ["copilot", "claude"]
    assert inputs["model"]["type"] == "string"
    assert inputs["rehearsal"]["default"] is False
    jobs = workflow["jobs"]
    assert jobs["get-entries"]["uses"] == "$/.github/workflows/get-entries.yml"
    assert jobs["get-entries"]["with"] == {"category": "bug-fix", "test-run": "${{ inputs.test-run }}"}
    evaluate = jobs["evaluate"]
    assert evaluate["runs-on"] == "GitHub-BCBench"
    assert evaluate["strategy"] == {
        "fail-fast": False,
        "max-parallel": 4,
        "matrix": {"entry": "${{ fromJson(needs.get-entries.outputs.entries) }}"},
    }


def test_tooling_precedes_restricted_setup_and_cli_uses_environment_contract() -> None:
    steps = _load(WORKFLOW)["jobs"]["evaluate"]["steps"]
    setup = _step(steps, "setup")
    assert setup["uses"] == "$/.github/actions/setup-bugfix-lifecycle"
    for action in ("setup-python-uv", "install-agent-harnesses"):
        assert next(i for i, step in enumerate(steps) if action in step.get("uses", "")) < steps.index(setup)
    assert next(i for i, step in enumerate(steps) if "actions/setup-node@" in step.get("uses", "")) < steps.index(setup)
    run = _step(steps, "evaluate")
    assert "uv run bcbench bugfix-lifecycle" in run["run"]
    for option in ("--entry-root", "--protected-root", "--dataset-path", "--output-dir"):
        assert option in run["run"]
    for secret_option in ("--password", "--agent-os-password", "--agent-bc-password", "--evaluator-container-config"):
        assert secret_option not in run["run"]
    assert "${{ inputs.model }}" not in run["run"]
    assert run["env"]["COPILOT_GITHUB_TOKEN"] == "${{ github.token }}"
    assert run["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "${{ secrets.ANTHROPIC_API_KEY }}"
    assert "$LASTEXITCODE" in run["run"]
    assert run["run"].index("Start-BCBenchWorkflowExecution") < run["run"].index("uv run bcbench bugfix-lifecycle")


def test_cleanup_and_separate_artifacts_always_run() -> None:
    steps = _load(WORKFLOW)["jobs"]["evaluate"]["steps"]
    cleanup = _step(steps, "cleanup")
    assert cleanup["if"] == "always()"
    assert "Complete-BugFixLifecycle.ps1" in cleanup["run"]
    results = _step(steps, "results")
    evidence = _step(steps, "evidence")
    quarantine = _step(steps, "quarantine")
    for step in (results, evidence, quarantine):
        assert "always()" in step["if"]
        assert step["uses"] == "actions/upload-artifact@v6"
        assert steps.index(step) > steps.index(cleanup)
    for step in (evidence, quarantine):
        assert "steps.paths.outputs.protected_root != ''" in step["if"]
    assert results["with"]["name"].startswith("evaluation-results-")
    assert results["with"]["path"] == "${{ env.EVALUATION_RESULTS_DIR }}/**/*.jsonl"
    assert not evidence["with"]["name"].startswith("evaluation-results-")
    assert "protected" in evidence["with"]["path"].lower()
    assert "quarantine.json" in quarantine["with"]["path"]
    check = _step(steps, "check-quarantine")
    assert check["if"] == "always()"
    assert "throw" in check["run"]


def test_summary_runs_after_failed_evaluation_without_parsing_evidence() -> None:
    summary = _load(WORKFLOW)["jobs"]["summarize-results"]
    assert "always()" in summary["if"]
    assert summary["with"]["production"] is True
    assert summary["with"]["skip-leaderboard"] is True
    assert summary["with"]["category"] == "bug-fix"
    config = _load(SUMMARY)
    production = config[True]["workflow_call"]["inputs"]["production"]
    assert production == {"description": "Use production lifecycle scoring", "required": False, "type": "boolean", "default": False}
    steps = config["jobs"]["summarize-results"]["steps"]
    download = next(step for step in steps if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"]["pattern"] == "evaluation-results-*"
    assert "${{ inputs.production && '--production' || '' }}" in _step(steps, "bceval")["run"]


def test_all_summary_callers_upload_matching_result_artifacts() -> None:
    for path in SUMMARY.parent.glob("*.yml"):
        workflow = _load(path)
        if not any(job.get("uses") == "$/.github/workflows/summarize-results.yml" for job in workflow["jobs"].values()):
            continue
        results = [
            step
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if step.get("uses", "").startswith("actions/upload-artifact@") and "*.jsonl" in step.get("with", {}).get("path", "")
        ]
        assert results, path
        for step in results:
            assert step["with"]["name"].startswith("evaluation-results-"), path


def test_setup_pins_helper_and_resolves_exact_dataset_before_tooling() -> None:
    action = _load(ACTION)
    steps = action["runs"]["steps"]
    source = ACTION.read_text(encoding="utf-8")
    assert "Install-Module -Name BcContainerHelper -RequiredVersion 6.1.18" in source
    assert any(step.get("uses") == "azure/login@v3" for step in steps)
    assert any(step.get("uses") == "actions/cache@v5" for step in steps)
    resolve = _step(steps, "resolve")["run"]
    assert "Get-BCBenchDatasetPath -Category bug-fix" in resolve
    assert "Get-BCBenchEntryVersion" in resolve
    assert "-DatasetPath $datasetPath" in resolve
    assert 'Major -lt 29) { "8.0" } else { "10.0" }' in resolve
    setup = _step(steps, "setup")["run"]
    assert "Setup-BugFixLifecycle.ps1" in setup
    assert "-DatasetPath $env:DATASET_PATH" in setup
    assert "-PythonExecutable" in setup
    assert "-ToolRoots" in setup
    assert steps.index(_step(steps, "al-tool")) < steps.index(_step(steps, "setup"))
    assert "18.0.37.11445-beta" in _step(steps, "al-tool")["run"]
    assert 'Write-Output "::add-mask::$password"' in setup
    for name in (
        "ENTRY_ROOT",
        "PROTECTED_ROOT",
        "DATASET_PATH",
        "AGENT_OS_USERNAME",
        "AGENT_OS_SID",
        "AGENT_BC_USERNAME",
        "EXPECTED_CONTAINER_ID",
        "EXPECTED_INVOCATION_ID",
        "STAGED_WORKER_PATH",
        "STAGED_WORKER_SHA256",
        "BASE_PYTHON",
        "PYTHON_BASE_PREFIX",
        "ACL_PATHS_JSON",
        "CLEANUP_TOOL_ROOTS_JSON",
        "OWNED_COMPILER_HELPER_ROOTS",
    ):
        assert action["outputs"][name.lower()]["value"] == "${{ steps.setup.outputs.BCBENCH_LIFECYCLE_" + name + " }}"
    assert not any("password" in name for name in action["outputs"])


@pytest.mark.skipif(PWSH is None, reason="PowerShell required")
@pytest.mark.parametrize(
    ("agent", "model", "rehearsal", "valid"),
    [
        ("copilot", "gpt-5.6-luna", "false", True),
        ("claude", "claude-haiku-4-5", "false", True),
        ("claude", "gpt-5.6-luna", "false", False),
        ("copilot", "claude-haiku-4-5", "false", False),
        ("other", "claude-sonnet-5", "false", False),
        ("copilot", "'; throw 'injected", "false", False),
        ("copilot", "gpt-5.6-luna", "true", False),
    ],
)
def test_dispatch_validation_uses_current_model_registry(agent: str, model: str, rehearsal: str, valid: bool) -> None:
    assert PWSH is not None
    step = _step(_load(WORKFLOW)["jobs"]["validate"]["steps"], "validate")
    assert "CopilotModel" in step["run"]
    assert "ClaudeCodeModel" in step["run"]
    assert "${{" not in step["run"]
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", step["run"]],
        cwd=ROOT,
        env={**os.environ, "AGENT": agent, "MODEL": model, "REHEARSAL": rehearsal},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is valid, result.stdout + result.stderr
    if rehearsal == "true":
        assert "not implemented" in result.stderr


@pytest.mark.skipif(PWSH is None, reason="PowerShell required")
@pytest.mark.parametrize(
    "scenario",
    [
        "never-launched",
        "already-clean",
        "replacement-id",
        "replacement-label",
        "remove-fails",
        "sid-replaced",
        "interrupted",
        "preexisting-quarantine",
        "owned-id-renamed",
        "unowned-path",
        "compiler-marker-mismatch",
        "plugin-marker-mismatch",
        "missing-container-id",
        "setup-quarantine",
        "launching",
        "cli_running",
        "running",
        "shutdown_verified",
        "missing-execution",
    ],
)
def test_workflow_finalizer_is_idempotent_and_ownership_safe(tmp_path: Path, scenario: str) -> None:
    module = ROOT / "scripts" / "BugFixLifecycle.psm1"
    entry = tmp_path / "entry"
    protected = tmp_path / "protected"
    entry.mkdir()
    protected.mkdir()
    (entry / "agent-workspace").mkdir()
    (entry / "agent-workspace" / "file.al").write_text("source")
    if scenario == "unowned-path":
        (entry / "unowned.txt").write_text("do not delete")
    state = {
        "Status": "provisioning" if scenario == "interrupted" else "ready",
        "InstanceId": "test",
        "ContainerName": "bc-test",
        "ContainerId": "owned-id",
        "ContainerInvocationId": "owned-label",
        "EntryRoot": str(entry),
        "ProtectedRoot": str(protected),
        "AgentIdentity": {"Username": "bcb-1234567-abcdef", "Sid": "S-1-5-21-1-2-3-1001"},
        "AgentBcIdentity": {"Username": "bca-1234567-abcdef"},
        "AclTransaction": {"Sid": "S-1-5-21-1-2-3-1001", "ModifiedPaths": [str(entry)], "CleanupComplete": False},
        "OwnedCompilerHelperRoots": [],
        "SetupCleanupErrors": [],
    }
    if scenario == "missing-container-id":
        state["ContainerId"] = ""
    if scenario == "plugin-marker-mismatch":
        plugins = entry / "agent-tools" / "plugins"
        plugins.mkdir(parents=True)
        (plugins / ".bcbench-owned").write_text("foreign-label")
    if scenario == "compiler-marker-mismatch":
        compiler = tmp_path / "compiler"
        compiler.mkdir()
        (compiler / ".bcbench-owned").write_text("not-our-invocation")
        state["OwnedCompilerHelperRoots"] = [str(compiler)]
    (protected / "workflow-setup.json").write_text(json.dumps(state), encoding="utf-8")
    execution_status = scenario if scenario in {"launching", "cli_running", "running", "shutdown_verified"} else "not_started"
    if scenario != "missing-execution":
        (protected / "workflow-execution.json").write_text(
            json.dumps(
                {
                    "status": execution_status,
                    "container_id": "owned-id",
                    "invocation_id": "owned-label",
                }
            ),
            encoding="utf-8",
        )
    evidence = protected / "final-results"
    evidence.mkdir()
    (evidence / "final-result.json").write_text('{"evidence":"preserve"}')
    if scenario == "preexisting-quarantine":
        (protected / "quarantine.json").write_text('{"reason":"client shutdown unverified"}')
    setup_quarantine = protected.with_name(protected.name + ".quarantine.json")
    if scenario == "setup-quarantine":
        setup_quarantine.write_text('{"reason":"setup rollback failed"}')
    script = r"""
$ErrorActionPreference = 'Stop'
Import-Module $env:MODULE -Force -DisableNameChecking
$global:present = $env:SCENARIO -notin @('already-clean', 'missing-container-id')
$global:identity = $env:SCENARIO -ne 'already-clean'
$global:calls = [Collections.Generic.List[string]]::new()
$ops = @{
    InspectContainer = {
        param($Context)
        [pscustomobject]@{
            Exists = $global:present -and $env:SCENARIO -ne 'owned-id-renamed'
            Id = if ($env:SCENARIO -eq 'replacement-id') { 'foreign-id' } else { 'owned-id' }
            InvocationId = if ($env:SCENARIO -eq 'replacement-label') { 'foreign-label' } else { 'owned-label' }
        }
    }
    InspectContainerById = {
        [pscustomobject]@{ Exists = ($global:present -or $env:SCENARIO -eq 'owned-id-renamed'); Id = 'owned-id'; InvocationId = 'owned-label' }
    }
    ReadAgentIdentity = {
        if ($global:identity) {
            [pscustomobject]@{ Sid = if ($env:SCENARIO -eq 'sid-replaced') { 'foreign-sid' } else { 'S-1-5-21-1-2-3-1001' } }
        }
    }
    StopServiceTier = { $global:calls.Add('stop') }
    RemoveBcIdentity = { $global:calls.Add('bc-user') }
    RemoveContainer = {
        $global:calls.Add('container')
        if ($env:SCENARIO -eq 'remove-fails') { throw 'forced container removal failure' }
        $global:present = $false
    }
    RemoveAcl = { $global:calls.Add('acl') }
    RemoveAgentIdentity = { $global:calls.Add('os-user'); $global:identity = $false }
    DisableAgentIdentity = { $global:calls.Add('disable') }
    VerifyAgentIdentityDisabled = { $global:calls.Add('verify-disabled') }
}
$message = ''
try {
    Complete-BCBenchBugFixLifecycle -EntryRoot $env:ENTRY -ProtectedRoot $env:PROTECTED -ContainerName bc-test -Operations $ops
    Complete-BCBenchBugFixLifecycle -EntryRoot $env:ENTRY -ProtectedRoot $env:PROTECTED -ContainerName bc-test -Operations $ops
} catch { $message = $_.Exception.Message }
@{ message = $message; calls = @($global:calls); entryExists = (Test-Path -LiteralPath $env:ENTRY) } | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "MODULE": str(module), "ENTRY": str(entry), "PROTECTED": str(protected), "SCENARIO": scenario},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.splitlines()[-1])
    assert "not recognized" not in payload["message"]
    assert (evidence / "final-result.json").read_text() == '{"evidence":"preserve"}'
    if scenario in {"never-launched", "already-clean", "shutdown_verified"}:
        assert payload["message"] == ""
        assert not payload["entryExists"]
        assert payload["calls"].count("container") == (0 if scenario == "already-clean" else 1)
        assert json.loads((protected / "workflow-cleanup.json").read_text(encoding="utf-8-sig"))["status"] == "success"
        assert not (protected / "quarantine.json").exists()
    else:
        assert payload["message"]
        assert payload["entryExists"]
        assert (protected / "quarantine.json").is_file()
        if scenario not in {"remove-fails", "unowned-path", "compiler-marker-mismatch", "plugin-marker-mismatch"}:
            assert "container" not in payload["calls"]
        if scenario == "sid-replaced":
            assert "disable" not in payload["calls"]
        else:
            assert "disable" in payload["calls"]
        if scenario == "setup-quarantine":
            assert setup_quarantine.read_text() == '{"reason":"setup rollback failed"}'


def test_workflow_setup_persists_only_nonsecret_cleanup_state() -> None:
    source = (ROOT / "scripts" / "BugFixLifecycle.psm1").read_text(encoding="utf-8")
    assert "function Write-BCBenchWorkflowSetupState" in source
    writer = source.split("function Write-BCBenchWorkflowSetupState", 1)[1].split("\nfunction ", 1)[0]
    assert "Password" not in writer
    assert "EvaluatorContainerConfig" not in writer
    assert "AgentContainerConfig" not in writer
    assert "workflow-setup.json" in writer
    assert "if ($createdProtectedRoot -and -not $WorkflowEvidence)" in source
    setup = (ROOT / "scripts" / "Setup-BugFixLifecycle.ps1").read_text(encoding="utf-8")
    assert "-WorkflowEvidence:$WorkflowEvidence" in setup
    finalizer = (ROOT / "scripts" / "Complete-BugFixLifecycle.ps1").read_text(encoding="utf-8")
    assert "Complete-BCBenchBugFixLifecycle" in finalizer


@pytest.mark.skipif(PWSH is None, reason="PowerShell required")
@pytest.mark.parametrize("scenario", ["no-setup", "daemon-unavailable", "missing-state"])
def test_finalizer_before_setup_or_without_ownership_state(tmp_path: Path, scenario: str) -> None:
    entry = tmp_path / "entry"
    protected = tmp_path / "new-parent" / "protected"
    if scenario == "missing-state":
        entry.mkdir()
        (entry / "keep.txt").write_text("unowned")
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            r"""
$ErrorActionPreference = 'Stop'
Import-Module $env:MODULE -Force -DisableNameChecking
$ops = @{ InspectContainer = {
    if ($env:SCENARIO -eq 'daemon-unavailable') { throw 'Docker daemon unavailable' }
    [pscustomobject]@{ Exists = $false; Id = $null; InvocationId = $null }
} }
$message = ''
try {
    Complete-BCBenchBugFixLifecycle -EntryRoot $env:ENTRY -ProtectedRoot $env:PROTECTED -ContainerName bc-test -Operations $ops
} catch { $message = $_.Exception.Message }
@{ message = $message } | ConvertTo-Json -Compress
""",
        ],
        env={**os.environ, "MODULE": str(ROOT / "scripts" / "BugFixLifecycle.psm1"), "ENTRY": str(entry), "PROTECTED": str(protected), "SCENARIO": scenario},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.splitlines()[-1])
    if scenario == "no-setup":
        assert payload["message"] == ""
        assert not protected.exists()
    else:
        assert "Workflow cleanup failed" in payload["message"]
        assert (protected / "quarantine.json").is_file()
        if scenario == "missing-state":
            assert (entry / "keep.txt").read_text() == "unowned"


@pytest.mark.skipif(PWSH is None, reason="PowerShell required")
def test_workflow_powershell_blocks_parse_without_expression_interpolation() -> None:
    blocks = []
    workflow = _load(WORKFLOW)
    for job in workflow["jobs"].values():
        blocks.extend(step["run"] for step in job.get("steps", []) if step.get("shell") == "pwsh")
    blocks.extend(step["run"] for step in _load(ACTION)["runs"]["steps"] if step.get("shell") == "pwsh")
    for block in blocks:
        assert "${{" not in block
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            r"""
$ErrorActionPreference = 'Stop'
foreach ($block in ($env:BLOCKS | ConvertFrom-Json)) {
    $tokens = $null
    $errors = $null
    [Management.Automation.Language.Parser]::ParseInput($block, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { throw ($errors | Out-String) }
}
""",
        ],
        env={**os.environ, "BLOCKS": json.dumps(blocks)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(PWSH is None, reason="PowerShell required")
@pytest.mark.parametrize(
    ("version", "repo", "duplicate", "framework", "internal"),
    [("28.5", "microsoft/BCApps", False, "8.0", "false"), ("29.0", "microsoftInternal/NAV", False, "10.0", "true"), ("28.5", "microsoft/BCApps", True, None, None)],
)
def test_setup_resolves_framework_and_auth_from_the_selected_dataset(
    tmp_path: Path,
    version: str,
    repo: str,
    duplicate: bool,
    framework: str | None,
    internal: str | None,
) -> None:
    dataset = tmp_path / "selected.jsonl"
    entry = create_dataset_entry(instance_id="workflow__entry-1", repo=repo, environment_setup_version=version)
    dataset.write_text((entry.model_dump_json() + "\n") * (2 if duplicate else 1), encoding="utf-8")
    output = tmp_path / "output"
    script = _step(_load(ACTION)["runs"]["steps"], "resolve")["run"].replace(
        "$datasetPath = Get-BCBenchDatasetPath",
        "function Get-BCBenchDatasetPath { param([string]$Category) $env:TEST_DATASET }\n$datasetPath = Get-BCBenchDatasetPath",
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env={**os.environ, "TEST_DATASET": str(dataset), "INSTANCE_ID": entry.instance_id, "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        check=False,
    )
    if duplicate:
        assert result.returncode != 0
        assert "Expected exactly one" in result.stderr
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8-sig").splitlines())
        assert values["dataset_path"] == str(dataset)
        assert values["version"] == version
        assert values["al_tool_dotnet_version"] == framework
        assert values["internal"] == internal
        assert values["cache_key"] == f"bcartifacts-{version}"


@pytest.mark.skipif(PWSH is None, reason="PowerShell required")
def test_setup_stops_on_native_python_resolution_failure() -> None:
    setup = _step(_load(ACTION)["runs"]["steps"], "setup")["run"]
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", "function uv { $global:LASTEXITCODE = 17; 'not-a-python-path' }\n" + setup],
        cwd=ROOT,
        env={**os.environ, "INTERNAL_REPO": "false"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Python resolution failed (17)" in result.stderr
