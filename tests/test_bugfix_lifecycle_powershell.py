import json
import os
import secrets
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from bcbench.types import ContainerConfig

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell lifecycle")

_ROOT = Path(__file__).parents[1]
_MODULE = _ROOT / "scripts" / "BugFixLifecycle.psm1"
_SETUP = _ROOT / "scripts" / "Setup-BugFixLifecycle.ps1"
_EXPECTED_EXPORTS = {
    "Assert-BCBenchReadExecuteRoots",
    "Get-BCBenchContainerState",
    "New-BCBenchAgentIdentity",
    "New-BCBenchAgentTools",
    "Remove-BCBenchAgentAcl",
    "Remove-BCBenchAgentIdentity",
    "Resolve-BCBenchPythonRuntime",
    "Set-BCBenchWorkspaceAcl",
    "Test-BCBenchIdentityAccess",
    "New-BCBenchAgentBcUser",
    "Remove-BCBenchAgentBcUser",
    "Invoke-BCBenchBugFixLifecycle",
}


def _ps_quote(value: str | Path) -> str:
    return f"'{str(value).replace("'", "''")}'"


def _run_pwsh(script: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, **(env or {})},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _last_json(output: str) -> object:
    return json.loads(output.splitlines()[-1])


def test_module_imports_and_exports_contract() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
Get-Command -Module BugFixLifecycle | Select-Object -ExpandProperty Name | ConvertTo-Json -Compress
"""
    exports = set(_last_json(_run_pwsh(script)))

    assert exports >= _EXPECTED_EXPORTS


def test_setup_parameter_metadata_and_pinned_container_helper() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile({_ps_quote(_SETUP)}, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) {{ throw ($errors | Out-String) }}
$metadata = @{{}}
foreach ($parameter in $ast.ParamBlock.Parameters) {{
    $metadata[$parameter.Name.VariablePath.UserPath] = @($parameter.Attributes | ForEach-Object {{ $_.Extent.Text }})
}}
$metadata | ConvertTo-Json -Compress -Depth 8
"""
    metadata = _last_json(_run_pwsh(script))
    source = _MODULE.read_text(encoding="utf-8") + _SETUP.read_text(encoding="utf-8")

    assert {
        "InstanceId",
        "Category",
        "DatasetPath",
        "Version",
        "ContainerName",
        "EvaluatorUsername",
        "EvaluatorPassword",
        "EntryRoot",
        "ProtectedRoot",
        "PythonExecutable",
        "ToolRoots",
        "AlMcp",
        "BcMcp",
    } <= metadata.keys()
    assert any('ValidateSet("bug-fix")' in attribute for attribute in metadata["Category"])
    assert "Import-Module BcContainerHelper -RequiredVersion 6.1.18" in source
    assert "New-BCContainerSync" in source
    assert 'Join-Path $EntryRoot "agent-tools"' in source
    assert '"--label"' in source
    assert '"bcbench.lifecycle.invocation=' in source
    assert "$effectiveToolRoots.Add((Split-Path $PSScriptRoot -Parent))" not in source
    assert 'foreach ($commandName in @("pwsh", "python", "git", "docker", "dotnet"))' not in source


def test_agent_tools_stages_exact_worker_hash_outside_benchmark(tmp_path: Path) -> None:
    entry_root = tmp_path / "entry"
    source_worker = _ROOT / "src" / "bcbench" / "agent" / "shared" / "contained_process_worker.py"
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$tools = New-BCBenchAgentTools `
    -EntryRoot {_ps_quote(entry_root)} `
    -BenchmarkRoot {_ps_quote(_ROOT)} `
    -SourceWorkerPath {_ps_quote(source_worker)}
[PSCustomObject]@{{
    tools = $tools
    sourceHash = (Get-FileHash -LiteralPath {_ps_quote(source_worker)} -Algorithm SHA256).Hash.ToLowerInvariant()
}} | ConvertTo-Json -Compress -Depth 6
"""
    payload = _last_json(_run_pwsh(script))
    worker = Path(payload["tools"]["WorkerPath"])

    assert Path(payload["tools"]["AgentTools"]).resolve() == (entry_root / "agent-tools").resolve()
    assert worker.resolve() == (entry_root / "agent-tools" / "contained_process_worker.py").resolve()
    assert not worker.is_relative_to(_ROOT)
    assert payload["tools"]["WorkerSha256"] == payload["sourceHash"]
    assert worker.read_bytes() == source_worker.read_bytes()


def test_setup_rejects_benchmark_root_as_explicit_tool_root(tmp_path: Path) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$message = $null
try {{
    & {_ps_quote(_SETUP)} `
        -InstanceId 'malicious-tool-root' `
        -DatasetPath {_ps_quote(_ROOT / "dataset" / "bcbench.jsonl")} `
        -EvaluatorUsername 'admin' `
        -EvaluatorPassword (ConvertTo-SecureString 'secret' -AsPlainText -Force) `
        -EntryRoot {_ps_quote(tmp_path / "entry")} `
        -ProtectedRoot {_ps_quote(tmp_path / "protected")} `
        -PythonExecutable {_ps_quote(sys.executable)} `
        -ToolRoots @({_ps_quote(_ROOT)})
}}
catch {{
    $message = $_.Exception.Message
}}
$message | ConvertTo-Json -Compress
"""
    message = _last_json(_run_pwsh(script))

    assert "must not overlap restricted benchmark or lifecycle paths" in message
    assert not (tmp_path / "entry").exists()
    assert not (tmp_path / "protected").exists()


def test_python_runtime_resolution_uses_uv_base_interpreter() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
Resolve-BCBenchPythonRuntime -PythonExecutable {_ps_quote(sys.executable)} | ConvertTo-Json -Compress -Depth 6
"""
    runtime = _last_json(_run_pwsh(script))

    assert Path(runtime["Executable"]).resolve() == Path(sys.executable).resolve()
    assert Path(runtime["BaseExecutable"]).is_file()
    assert Path(runtime["BasePrefix"]).is_dir()
    assert Path(runtime["Prefix"]).resolve() == Path(sys.prefix).resolve()
    assert Path(runtime["BaseExecutable"]).resolve() != Path(runtime["Executable"]).resolve()
    assert Path(runtime["BasePrefix"]).resolve() != Path(runtime["Prefix"]).resolve()


def test_python_runtime_resolution_honors_reported_base_executable(tmp_path: Path) -> None:
    launcher = tmp_path / "fake-python.ps1"
    executable = tmp_path / "venv" / "Scripts" / "python.exe"
    base_prefix = tmp_path / "base-runtime"
    prefix = tmp_path / "venv"
    executable.parent.mkdir(parents=True)
    base_prefix.mkdir()
    executable.touch()
    base_executable = base_prefix / "python.exe"
    base_executable.touch()
    launcher.write_text(
        f"""@{{
    executable = '{str(executable).replace("'", "''")}'
    base_executable = '{str(base_executable).replace("'", "''")}'
    base_prefix = '{str(base_prefix).replace("'", "''")}'
    prefix = '{str(prefix).replace("'", "''")}'
}} | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
Resolve-BCBenchPythonRuntime -PythonExecutable {_ps_quote(launcher)} | ConvertTo-Json -Compress -Depth 6
"""
    runtime = _last_json(_run_pwsh(script))

    assert Path(runtime["Executable"]).resolve() == executable.resolve()
    assert Path(runtime["BaseExecutable"]).resolve() == base_executable.resolve()
    assert Path(runtime["BasePrefix"]).resolve() == base_prefix.resolve()
    assert Path(runtime["Prefix"]).resolve() == prefix.resolve()


@pytest.mark.parametrize("restricted_name", ["benchmark", "protected"])
def test_runtime_root_rejects_restricted_storage(tmp_path: Path, restricted_name: str) -> None:
    benchmark = tmp_path / "benchmark"
    dataset = benchmark / "dataset" / "bcbench.jsonl"
    protected = tmp_path / "protected"
    entry = tmp_path / "entry"
    dataset.parent.mkdir(parents=True)
    dataset.touch()
    protected.mkdir()
    entry.mkdir()
    restricted_root = {"benchmark": benchmark, "protected": protected}[restricted_name]
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$message = $null
try {{
    Assert-BCBenchReadExecuteRoots `
        -ReadExecuteRoots @({_ps_quote(restricted_root)}) `
        -BenchmarkRoot {_ps_quote(benchmark)} `
        -DatasetPath {_ps_quote(dataset)} `
        -ProtectedRoot {_ps_quote(protected)} `
        -EntryRoot {_ps_quote(entry)} `
        -AllowedAgentRoots @() `
        -RestrictedLifecycleRoots @()
}}
catch {{
    $message = $_.Exception.Message
}}
$message | ConvertTo-Json -Compress
"""
    message = _last_json(_run_pwsh(script))

    assert "must not overlap restricted benchmark or lifecycle paths" in message


def test_new_agent_identity_retries_collision_and_never_adds_privileged_groups() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$global:getCalls = 0
$global:newUsers = @()
$global:groups = @()
function global:Get-LocalUser {{
    param([string]$Name)
    $global:getCalls++
    if ($global:getCalls -eq 1) {{ return [PSCustomObject]@{{ Name = $Name }} }}
    return $null
}}
function global:New-LocalUser {{
    param([string]$Name, [SecureString]$Password, [string]$Description, [switch]$AccountNeverExpires, [switch]$PasswordNeverExpires)
    $global:newUsers += $Name
    [PSCustomObject]@{{ Name = $Name; Sid = 'S-1-5-21-1000-1001-1002-1003' }}
}}
function global:Add-LocalGroupMember {{
    param($SID, $Member)
    $global:groups += [string]$SID
}}
function global:Get-LocalGroupMember {{ @() }}
Import-Module {_ps_quote(_MODULE)} -Force
$identity = New-BCBenchAgentIdentity -InstanceId 'bug-fix__entry/unsafe'
[PSCustomObject]@{{
    identity = $identity
    getCalls = $global:getCalls
    newUsers = $global:newUsers
    groups = $global:groups
}} | ConvertTo-Json -Compress -Depth 6
"""
    payload = _last_json(_run_pwsh(script))

    assert payload["getCalls"] >= 2
    assert len(payload["newUsers"]) == 1
    assert payload["identity"]["Username"].startswith("bcb-")
    assert payload["identity"]["Sid"] == "S-1-5-21-1000-1001-1002-1003"
    assert len(payload["identity"]["Username"]) <= 20
    assert payload["identity"]["Password"]
    assert payload["identity"]["Domain"]
    assert payload["groups"] == ["S-1-5-32-545"]
    assert "S-1-5-32-544" not in payload["groups"]
    assert "docker-users" not in payload["groups"]


def test_remove_agent_identity_propagates_local_user_provider_errors() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$global:errorAction = $null
function global:Get-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)

    $global:errorAction = [string]$PSBoundParameters.ErrorAction
    $errorRecord = [Management.Automation.ErrorRecord]::new(
        [InvalidOperationException]::new('local user provider unavailable'),
        'ProviderUnavailable',
        [Management.Automation.ErrorCategory]::ResourceUnavailable,
        $Name
    )
    $PSCmdlet.ThrowTerminatingError($errorRecord)
}}
Import-Module {_ps_quote(_MODULE)} -Force
$message = $null
try {{
    Remove-BCBenchAgentIdentity -Username 'bcb-1234567-abcdef'
}}
catch {{
    $message = $_.Exception.Message
}}
[PSCustomObject]@{{
    message = $message
    errorAction = $global:errorAction
}} | ConvertTo-Json -Compress
"""
    payload = _last_json(_run_pwsh(script))

    assert payload == {
        "message": "local user provider unavailable",
        "errorAction": "Stop",
    }


def test_remove_agent_identity_accepts_only_true_missing_user() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$global:removeCalls = 0
function global:Get-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)

    $errorRecord = [Management.Automation.ErrorRecord]::new(
        [Management.Automation.ItemNotFoundException]::new("User $Name was not found."),
        'UserNotFound',
        [Management.Automation.ErrorCategory]::ObjectNotFound,
        $Name
    )
    $PSCmdlet.ThrowTerminatingError($errorRecord)
}}
function global:Remove-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)
    $global:removeCalls++
}}
Import-Module {_ps_quote(_MODULE)} -Force
Remove-BCBenchAgentIdentity -Username 'bcb-1234567-abcdef'
$global:removeCalls | ConvertTo-Json -Compress
"""
    remove_calls = _last_json(_run_pwsh(script))

    assert remove_calls == 0


def test_remove_agent_identity_propagates_removal_errors() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$global:errorAction = $null
function global:Get-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)
    [PSCustomObject]@{{ Name = $Name; Enabled = $true }}
}}
function global:Remove-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)
    $global:errorAction = [string]$PSBoundParameters.ErrorAction
    throw 'identity removal failed'
}}
Import-Module {_ps_quote(_MODULE)} -Force
$message = $null
try {{
    Remove-BCBenchAgentIdentity -Username 'bcb-1234567-abcdef'
}}
catch {{
    $message = $_.Exception.Message
}}
[PSCustomObject]@{{
    message = $message
    errorAction = $global:errorAction
}} | ConvertTo-Json -Compress
"""
    payload = _last_json(_run_pwsh(script))

    assert payload == {
        "message": "identity removal failed",
        "errorAction": "Stop",
    }


def test_new_agent_identity_rollback_disables_and_verifies_when_removal_fails() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$global:user = $null
$global:disableCalls = 0
$global:getCalls = 0
function global:Get-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)
    $global:getCalls++
    return $global:user
}}
function global:New-LocalUser {{
    [CmdletBinding()]
    param([string]$Name, [SecureString]$Password, [string]$Description, [switch]$AccountNeverExpires, [switch]$PasswordNeverExpires)
    $global:user = [PSCustomObject]@{{ Name = $Name; Enabled = $true; Sid = 'S-1-5-21-1000-1001-1002-1003' }}
    return $global:user
}}
function global:Add-LocalGroupMember {{
    [CmdletBinding()]
    param($SID, $Member)
    throw 'identity creation failed'
}}
function global:Remove-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)
    throw 'identity removal failed'
}}
function global:Disable-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)
    $global:disableCalls++
    $global:user.Enabled = $false
}}
Import-Module {_ps_quote(_MODULE)} -Force
$exception = $null
try {{
    New-BCBenchAgentIdentity -InstanceId 'rollback-disable' | Out-Null
}}
catch {{
    $exception = $_.Exception
}}
[PSCustomObject]@{{
    type = $exception.GetType().FullName
    messages = @($exception.InnerExceptions | ForEach-Object {{ $_.Message }})
    disableCalls = $global:disableCalls
    enabled = $global:user.Enabled
    getCalls = $global:getCalls
}} | ConvertTo-Json -Compress -Depth 6
"""
    payload = _last_json(_run_pwsh(script))

    assert payload["type"] == "System.AggregateException"
    assert payload["messages"] == ["identity creation failed", "identity removal failed"]
    assert payload["disableCalls"] == 1
    assert payload["enabled"] is False
    assert payload["getCalls"] >= 2


def test_new_agent_identity_rollback_aggregates_removal_and_disable_failures() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$global:user = $null
$global:verifyCalls = 0
function global:Get-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)
    if ($null -ne $global:user) {{ $global:verifyCalls++ }}
    return $global:user
}}
function global:New-LocalUser {{
    [CmdletBinding()]
    param([string]$Name, [SecureString]$Password, [string]$Description, [switch]$AccountNeverExpires, [switch]$PasswordNeverExpires)
    $global:user = [PSCustomObject]@{{ Name = $Name; Enabled = $true; Sid = 'S-1-5-21-1000-1001-1002-1003' }}
    return $global:user
}}
function global:Add-LocalGroupMember {{
    [CmdletBinding()]
    param($SID, $Member)
    throw 'identity creation failed'
}}
function global:Remove-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)
    throw 'identity removal failed'
}}
function global:Disable-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)
    $global:user.Enabled = $false
    throw 'identity disable failed'
}}
Import-Module {_ps_quote(_MODULE)} -Force
$exception = $null
try {{
    New-BCBenchAgentIdentity -InstanceId 'rollback-disable-failure' | Out-Null
}}
catch {{
    $exception = $_.Exception
}}
[PSCustomObject]@{{
    type = $exception.GetType().FullName
    messages = @($exception.InnerExceptions | ForEach-Object {{ $_.Message }})
    enabled = $global:user.Enabled
    verifyCalls = $global:verifyCalls
}} | ConvertTo-Json -Compress -Depth 6
"""
    payload = _last_json(_run_pwsh(script))

    assert payload["type"] == "System.AggregateException"
    assert payload["messages"] == [
        "identity creation failed",
        "identity removal failed",
        "identity disable failed",
    ]
    assert payload["enabled"] is False
    assert payload["verifyCalls"] >= 1


def test_workspace_acl_uses_exact_checked_icacls_commands_and_runs_access_validator(tmp_path: Path) -> None:
    entry_root = tmp_path / "entry"
    paths = {
        name: entry_root / name
        for name in (
            "baseline",
            "agent",
            "logs",
            "agent-tools",
            "staging",
            "evaluators",
            "evidence",
        )
    }
    paths["entry"] = entry_root
    paths["protected"] = tmp_path / "protected"
    paths["tool"] = tmp_path / "tool"
    paths["runtime"] = tmp_path / "runtime"
    paths["benchmark"] = tmp_path / "benchmark"
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    dataset_path = paths["benchmark"] / "dataset" / "bcbench.jsonl"
    dataset_path.parent.mkdir()
    dataset_path.touch()
    runtime_executable = tmp_path / "venv" / "Scripts" / "python.exe"
    runtime_executable.parent.mkdir(parents=True)
    runtime_executable.touch()
    source_worker_path = paths["benchmark"] / "src" / "bcbench" / "agent" / "shared" / "contained_process_worker.py"
    source_worker_path.parent.mkdir(parents=True)
    (paths["benchmark"] / "src" / "bcbench" / "evaluate").mkdir(parents=True)
    (paths["benchmark"] / "docs").mkdir()
    source_worker_path.write_text("print('worker')\n", encoding="utf-8")
    worker_path = paths["agent-tools"] / "contained_process_worker.py"
    worker_path.write_bytes(source_worker_path.read_bytes())
    worker_hash = sha256(source_worker_path.read_bytes()).hexdigest()
    worker_request_path = paths["staging"] / "worker-request.json"
    gate_path = paths["staging"] / "launch.gate"
    output_parent = paths["staging"] / "output"
    output_parent.mkdir()
    stdout_path = output_parent / "stdout.txt"
    stderr_path = output_parent / "stderr.txt"
    for path in (worker_request_path, gate_path, stdout_path, stderr_path):
        path.touch()
    script = f"""
$ErrorActionPreference = 'Stop'
$global:icaclsCalls = @()
$global:verificationCalls = @()
$icaclsRunner = {{
    param([string[]]$Arguments)
    $global:icaclsCalls += ,@($Arguments)
    return 0
}}
$aclVerifier = {{
    param($Parameters)
    $global:verificationCalls += $Parameters
}}
$validator = {{
    param($Parameters)
    [PSCustomObject]@{{
        WorkspaceWriteSucceeded = $true
        ProtectedReadDenied = $true
        ProtectedWriteDenied = $true
        BenchmarkWriteDenied = $true
        DatasetReadDenied = $true
        EvaluatorSourceReadDenied = $true
        DocsReadDenied = $true
        AgentToolsWriteDenied = $true
        ReadExecuteDirectoryReadSucceeded = $true
        ReadExecuteDirectoryCreateDenied = $true
        ReadExecuteDirectoryWriteDenied = $true
        ReadExecuteDirectoryDeleteDenied = $true
        ReadExecuteFileReadSucceeded = $true
        ReadExecuteFileModifyDenied = $true
        RuntimeExecutableExecutionSucceeded = $true
        DockerCliDenied = $true
        DockerPipeDenied = $true
        MountedStagingCreateDenied = $true
        MountedStagingWriteDenied = $true
        MountedStagingDeleteDenied = $true
        OutputParentCreateDenied = $true
        OutputParentWriteDenied = $true
        OutputParentDeleteDenied = $true
        OutputFileOpenDenied = $true
        OutputHandleCaptureSucceeded = $true
        ProcessId = 1234
        WorkspaceProbePath = 'probe'
        ProtectedProbePath = 'secret'
    }}
}}
Import-Module {_ps_quote(_MODULE)} -Force
$identity = [PSCustomObject]@{{
    Username = 'bcb-1234567-abcdef'
    Password = 'secret'
    Domain = '.'
    Sid = 'S-1-5-21-1000-1001-1002-1003'
}}
$result = Set-BCBenchWorkspaceAcl `
    -Identity $identity `
    -EntryRoot {_ps_quote(paths["entry"])} `
    -BaselineWorkspace {_ps_quote(paths["baseline"])} `
    -AgentWorkspace {_ps_quote(paths["agent"])} `
    -AgentLogs {_ps_quote(paths["logs"])} `
    -AgentTools {_ps_quote(paths["agent-tools"])} `
    -MountedStaging {_ps_quote(paths["staging"])} `
    -EvaluatorWorkspaces {_ps_quote(paths["evaluators"])} `
    -Evidence {_ps_quote(paths["evidence"])} `
    -ProtectedRoot {_ps_quote(paths["protected"])} `
    -BenchmarkRoot {_ps_quote(paths["benchmark"])} `
    -DatasetPath {_ps_quote(dataset_path)} `
    -ToolRoots @({_ps_quote(paths["tool"])}) `
    -RuntimeExecutablePaths @({_ps_quote(runtime_executable)}) `
    -RuntimeRoots @({_ps_quote(paths["runtime"])}) `
    -SourceWorkerPath {_ps_quote(source_worker_path)} `
    -WorkerPath {_ps_quote(worker_path)} `
    -WorkerSha256 '{worker_hash}' `
    -WorkerRequestPaths @({_ps_quote(worker_request_path)}, {_ps_quote(gate_path)}) `
    -IcaclsRunner $icaclsRunner `
    -AclVerifier $aclVerifier `
    -AccessValidator $validator
$agentAccount = "$([Environment]::MachineName)\\bcb-1234567-abcdef"
[PSCustomObject]@{{
    calls = $global:icaclsCalls
    verificationCalls = $global:verificationCalls
    evaluatorAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    agentAccount = $agentAccount
    result = $result
}} | ConvertTo-Json -Compress -Depth 8
"""
    payload = _last_json(_run_pwsh(script))
    evaluator = payload["evaluatorAccount"]
    agent = payload["agentAccount"]
    full_control = [f"{evaluator}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"]
    expected_calls = [
        [str(paths["benchmark"]), "/deny", f"{agent}:(OI)(CI)F"],
        [str(paths["entry"]), "/inheritance:r"],
        [str(paths["entry"]), "/grant:r", *full_control, f"{agent}:(X)"],
    ]
    for path in (paths["baseline"], paths["staging"], paths["evaluators"], paths["evidence"], paths["protected"]):
        expected_calls.extend(
            [
                [str(path), "/inheritance:r"],
                [str(path), "/grant:r", *full_control],
                [str(path), "/remove:g", agent],
            ]
        )
    for path in (paths["agent"], paths["logs"]):
        expected_calls.extend(
            [
                [str(path), "/inheritance:r"],
                [str(path), "/grant:r", *full_control, f"{agent}:(OI)(CI)M"],
            ]
        )
    expected_calls.extend(
        [
            [str(paths["agent-tools"]), "/grant:r", f"{agent}:(OI)(CI)RX"],
            [
                str(paths["agent-tools"]),
                "/deny",
                "*S-1-5-21-1000-1001-1002-1003:(OI)(CI)(WD,AD,WEA,WA,DE,DC,WDAC,WO)",
            ],
            [str(worker_path), "/grant:r", f"{agent}:RX"],
            [
                str(worker_path),
                "/deny",
                "*S-1-5-21-1000-1001-1002-1003:(WD,AD,WEA,WA,DE,WDAC,WO)",
            ],
        ]
    )
    expected_calls.extend(
        [
            [str(paths["tool"]), "/grant:r", f"{agent}:(OI)(CI)RX"],
            [
                str(paths["tool"]),
                "/deny",
                "*S-1-5-21-1000-1001-1002-1003:(OI)(CI)(WD,AD,WEA,WA,DE,DC,WDAC,WO)",
            ],
            [str(paths["runtime"]), "/grant:r", f"{agent}:(OI)(CI)RX"],
            [
                str(paths["runtime"]),
                "/deny",
                "*S-1-5-21-1000-1001-1002-1003:(OI)(CI)(WD,AD,WEA,WA,DE,DC,WDAC,WO)",
            ],
            [str(runtime_executable), "/grant:r", f"{agent}:RX"],
            [
                str(runtime_executable),
                "/deny",
                "*S-1-5-21-1000-1001-1002-1003:(WD,AD,WEA,WA,DE,WDAC,WO)",
            ],
        ]
    )
    expected_calls.extend(
        [
            [str(paths["staging"]), "/inheritance:r"],
            [str(paths["staging"]), "/grant:r", *full_control, f"{agent}:(X)"],
            [str(worker_request_path), "/grant:r", f"{agent}:R"],
            [
                str(worker_request_path),
                "/deny",
                "*S-1-5-21-1000-1001-1002-1003:(WD,AD,WEA,WA,DE,WDAC,WO)",
            ],
            [str(gate_path), "/grant:r", f"{agent}:R"],
            [
                str(gate_path),
                "/deny",
                "*S-1-5-21-1000-1001-1002-1003:(WD,AD,WEA,WA,DE,WDAC,WO)",
            ],
        ]
    )

    assert payload["calls"] == expected_calls
    assert len(payload["verificationCalls"]) == 24
    deny_verifications = [item for item in payload["verificationCalls"] if item["ExpectedRules"][0].get("AccessControlType") == "Deny" and item["Path"] != str(paths["benchmark"])]
    assert len(deny_verifications) == 7
    assert {item["ExpectedRules"][0]["Identity"] for item in deny_verifications} == {"S-1-5-21-1000-1001-1002-1003"}
    assert {item["ExpectedRules"][0]["Rights"] for item in deny_verifications} == {
        "WriteData, AppendData, WriteExtendedAttributes, WriteAttributes, Delete, DeleteSubdirectoriesAndFiles, ChangePermissions, TakeOwnership",
        "WriteData, AppendData, WriteExtendedAttributes, WriteAttributes, Delete, ChangePermissions, TakeOwnership",
    }
    assert all("*" not in call[0] and "?" not in call[0] for call in payload["calls"])
    restricted_agent_grant_paths = {Path(call[0]).resolve() for call in payload["calls"] if "/grant:r" in call and any(agent in value for value in call[2:])}
    assert Path(paths["benchmark"]).resolve() not in restricted_agent_grant_paths
    assert dataset_path.resolve() not in restricted_agent_grant_paths
    assert (paths["benchmark"] / "docs").resolve() not in restricted_agent_grant_paths
    assert (paths["benchmark"] / "src" / "bcbench" / "evaluate").resolve() not in restricted_agent_grant_paths
    assert Path(paths["protected"]).resolve() not in restricted_agent_grant_paths
    assert Path(paths["baseline"]).resolve() not in restricted_agent_grant_paths
    assert Path(paths["evaluators"]).resolve() not in restricted_agent_grant_paths
    assert Path(paths["evidence"]).resolve() not in restricted_agent_grant_paths
    assert stdout_path.resolve() not in restricted_agent_grant_paths
    assert stderr_path.resolve() not in restricted_agent_grant_paths
    assert worker_path.resolve().is_relative_to(paths["agent-tools"].resolve())
    assert payload["result"]["ProcessId"] == 1234
    assert payload["result"]["AclTransaction"]["Sid"] == "S-1-5-21-1000-1001-1002-1003"
    assert {Path(path).resolve() for path in payload["result"]["AclTransaction"]["ModifiedPaths"]} == {
        Path(path).resolve()
        for path in (
            paths["benchmark"],
            paths["entry"],
            paths["baseline"],
            paths["agent"],
            paths["logs"],
            paths["agent-tools"],
            paths["staging"],
            paths["evaluators"],
            paths["evidence"],
            paths["protected"],
            paths["tool"],
            paths["runtime"],
            runtime_executable,
            worker_path,
            worker_request_path,
            gate_path,
        )
    }
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$parameters = (Get-Command Set-BCBenchWorkspaceAcl).Parameters.Keys
[PSCustomObject]@{{
    hasWorkerOutputPaths = $parameters -contains 'WorkerOutputPaths'
    sourceUsesWorkerOutputPaths = [IO.File]::ReadAllText({_ps_quote(_MODULE)}).Contains('WorkerOutputPaths')
}} | ConvertTo-Json -Compress
"""
    output_contract = _last_json(_run_pwsh(script))
    assert output_contract == {
        "hasWorkerOutputPaths": False,
        "sourceUsesWorkerOutputPaths": False,
    }


def test_workspace_acl_rejects_any_writable_read_execute_path(tmp_path: Path) -> None:
    entry_root = tmp_path / "entry"
    paths = {
        name: entry_root / name
        for name in (
            "baseline",
            "agent",
            "logs",
            "agent-tools",
            "staging",
            "evaluators",
            "evidence",
        )
    }
    paths["protected"] = tmp_path / "protected"
    paths["tool"] = tmp_path / "tool"
    paths["runtime"] = tmp_path / "runtime"
    paths["benchmark"] = tmp_path / "benchmark"
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    dataset_path = paths["benchmark"] / "dataset" / "bcbench.jsonl"
    dataset_path.parent.mkdir()
    dataset_path.touch()
    runtime_executable = paths["runtime"] / "python.exe"
    runtime_executable.touch()
    source_worker_path = paths["benchmark"] / "src" / "bcbench" / "agent" / "shared" / "contained_process_worker.py"
    source_worker_path.parent.mkdir(parents=True)
    (paths["benchmark"] / "src" / "bcbench" / "evaluate").mkdir(parents=True)
    (paths["benchmark"] / "docs").mkdir()
    source_worker_path.write_text("print('worker')\n", encoding="utf-8")
    worker_path = paths["agent-tools"] / "contained_process_worker.py"
    worker_path.write_bytes(source_worker_path.read_bytes())
    worker_hash = sha256(source_worker_path.read_bytes()).hexdigest()
    script = f"""
$ErrorActionPreference = 'Stop'
$global:calls = @()
Import-Module {_ps_quote(_MODULE)} -Force
$identity = [PSCustomObject]@{{
    Username = 'bcb-1234567-abcdef'
    Password = 'secret'
    Domain = '.'
    Sid = 'S-1-5-21-1000-1001-1002-1003'
}}
$message = $null
try {{
    Set-BCBenchWorkspaceAcl `
        -Identity $identity `
        -EntryRoot {_ps_quote(entry_root)} `
        -BaselineWorkspace {_ps_quote(paths["baseline"])} `
        -AgentWorkspace {_ps_quote(paths["agent"])} `
        -AgentLogs {_ps_quote(paths["logs"])} `
        -AgentTools {_ps_quote(paths["agent-tools"])} `
        -MountedStaging {_ps_quote(paths["staging"])} `
        -EvaluatorWorkspaces {_ps_quote(paths["evaluators"])} `
        -Evidence {_ps_quote(paths["evidence"])} `
        -ProtectedRoot {_ps_quote(paths["protected"])} `
        -BenchmarkRoot {_ps_quote(paths["benchmark"])} `
        -DatasetPath {_ps_quote(dataset_path)} `
        -ToolRoots @({_ps_quote(paths["tool"])}) `
        -RuntimeExecutablePaths @({_ps_quote(runtime_executable)}) `
        -RuntimeRoots @({_ps_quote(paths["runtime"])}) `
        -SourceWorkerPath {_ps_quote(source_worker_path)} `
        -WorkerPath {_ps_quote(worker_path)} `
        -WorkerSha256 '{worker_hash}' `
        -IcaclsRunner {{
            param([string[]]$Arguments)
            $global:calls += ,@($Arguments)
            return 0
        }} `
        -AclVerifier {{ }} `
        -AccessValidator {{
            [PSCustomObject]@{{
                WorkspaceWriteSucceeded = $true
                ProtectedReadDenied = $true
                ProtectedWriteDenied = $true
                BenchmarkWriteDenied = $true
                DatasetReadDenied = $true
                EvaluatorSourceReadDenied = $true
                DocsReadDenied = $true
                AgentToolsWriteDenied = $true
                ReadExecuteDirectoryReadSucceeded = $true
                ReadExecuteDirectoryCreateDenied = $false
                ReadExecuteDirectoryWriteDenied = $true
                ReadExecuteDirectoryDeleteDenied = $true
                ReadExecuteFileReadSucceeded = $true
                ReadExecuteFileModifyDenied = $true
                RuntimeExecutableExecutionSucceeded = $true
                DockerCliDenied = $true
                DockerPipeDenied = $true
                MountedStagingCreateDenied = $true
                MountedStagingWriteDenied = $true
                MountedStagingDeleteDenied = $true
                OutputParentCreateDenied = $true
                OutputParentWriteDenied = $true
                OutputParentDeleteDenied = $true
                OutputFileOpenDenied = $true
                OutputHandleCaptureSucceeded = $true
            }}
        }} | Out-Null
}}
catch {{
    $message = $_.Exception.Message
}}
[PSCustomObject]@{{ message = $message; calls = $global:calls }} | ConvertTo-Json -Compress -Depth 8
"""
    payload = _last_json(_run_pwsh(script))

    assert "ReadExecuteDirectoryCreateDenied was false" in payload["message"]
    assert any(call[1:] == ["/remove:g", "*S-1-5-21-1000-1001-1002-1003"] for call in payload["calls"])
    assert any(call[1:] == ["/remove:d", "*S-1-5-21-1000-1001-1002-1003"] for call in payload["calls"])


@pytest.mark.parametrize(
    "malicious_path_name",
    [
        "benchmark",
        "benchmark-parent",
        "dataset",
        "docs",
        "evaluator",
        "protected",
        "baseline",
        "staging",
        "evaluators",
        "evidence",
        "unknown-sibling",
    ],
)
def test_workspace_acl_rejects_malicious_tool_roots(tmp_path: Path, malicious_path_name: str) -> None:
    benchmark = tmp_path / "benchmark"
    entry_root = tmp_path / "entry"
    protected = tmp_path / "protected"
    paths = {
        "baseline": entry_root / "baseline",
        "agent": entry_root / "agent",
        "logs": entry_root / "logs",
        "agent-tools": entry_root / "agent-tools",
        "staging": entry_root / "staging",
        "evaluators": entry_root / "evaluators",
        "evidence": entry_root / "evidence",
    }
    dataset = benchmark / "dataset" / "bcbench.jsonl"
    docs = benchmark / "docs"
    evaluator = benchmark / "src" / "bcbench" / "evaluate"
    unknown_sibling = entry_root / "unknown-sibling"
    source_worker = benchmark / "src" / "bcbench" / "agent" / "shared" / "contained_process_worker.py"
    worker = paths["agent-tools"] / "contained_process_worker.py"
    for directory in (*paths.values(), protected, docs, evaluator, unknown_sibling, source_worker.parent):
        directory.mkdir(parents=True, exist_ok=True)
    dataset.parent.mkdir(parents=True, exist_ok=True)
    dataset.touch()
    source_worker.write_text("print('worker')\n", encoding="utf-8")
    worker.write_bytes(source_worker.read_bytes())
    worker_hash = sha256(source_worker.read_bytes()).hexdigest()
    malicious_paths = {
        "benchmark": benchmark,
        "benchmark-parent": tmp_path,
        "dataset": dataset.parent,
        "docs": docs,
        "evaluator": evaluator,
        "protected": protected,
        "unknown-sibling": unknown_sibling,
        **paths,
    }
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$identity = [PSCustomObject]@{{
    Username = 'bcb-1234567-abcdef'
    Password = 'secret'
    Domain = '.'
    Sid = 'S-1-5-21-1000-1001-1002-1003'
}}
$message = $null
try {{
    Set-BCBenchWorkspaceAcl `
        -Identity $identity `
        -EntryRoot {_ps_quote(entry_root)} `
        -BaselineWorkspace {_ps_quote(paths["baseline"])} `
        -AgentWorkspace {_ps_quote(paths["agent"])} `
        -AgentLogs {_ps_quote(paths["logs"])} `
        -AgentTools {_ps_quote(paths["agent-tools"])} `
        -MountedStaging {_ps_quote(paths["staging"])} `
        -EvaluatorWorkspaces {_ps_quote(paths["evaluators"])} `
        -Evidence {_ps_quote(paths["evidence"])} `
        -ProtectedRoot {_ps_quote(protected)} `
        -BenchmarkRoot {_ps_quote(benchmark)} `
        -DatasetPath {_ps_quote(dataset)} `
        -ToolRoots @({_ps_quote(malicious_paths[malicious_path_name])}) `
        -RuntimeExecutablePaths @() `
        -RuntimeRoots @() `
        -SourceWorkerPath {_ps_quote(source_worker)} `
        -WorkerPath {_ps_quote(worker)} `
        -WorkerSha256 '{worker_hash}' `
        -IcaclsRunner {{ return 0 }} `
        -AclVerifier {{ }} `
        -AccessValidator {{ throw 'must not validate' }} | Out-Null
}}
catch {{
    $message = $_.Exception.Message
}}
$message | ConvertTo-Json -Compress
"""
    message = _last_json(_run_pwsh(script))

    assert "must not overlap restricted benchmark or lifecycle paths" in message


def test_workspace_acl_stops_on_icacls_failure(tmp_path: Path) -> None:
    entry_root = tmp_path / "entry"
    paths = {
        name: entry_root / name
        for name in (
            "baseline",
            "agent",
            "logs",
            "agent-tools",
            "staging",
            "evaluators",
            "evidence",
        )
    }
    paths["entry"] = entry_root
    paths["protected"] = tmp_path / "protected"
    paths["tool"] = tmp_path / "tool"
    paths["benchmark"] = tmp_path / "benchmark"
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    dataset_path = paths["benchmark"] / "dataset" / "bcbench.jsonl"
    dataset_path.parent.mkdir()
    dataset_path.touch()
    runtime_executable = tmp_path / "python.exe"
    runtime_executable.touch()
    source_worker_path = paths["benchmark"] / "src" / "bcbench" / "agent" / "shared" / "contained_process_worker.py"
    source_worker_path.parent.mkdir(parents=True)
    (paths["benchmark"] / "src" / "bcbench" / "evaluate").mkdir(parents=True)
    (paths["benchmark"] / "docs").mkdir()
    source_worker_path.write_text("print('worker')\n", encoding="utf-8")
    worker_path = paths["agent-tools"] / "contained_process_worker.py"
    worker_path.write_bytes(source_worker_path.read_bytes())
    worker_hash = sha256(source_worker_path.read_bytes()).hexdigest()
    script = f"""
$ErrorActionPreference = 'Stop'
$global:calls = @()
$global:validated = $false
$runner = {{
    param([string[]]$Arguments)
    $global:calls += ,@($Arguments)
    if ($global:calls.Count -eq 2) {{ return 5 }}
    return 0
}}
$validator = {{
    $global:validated = $true
    throw 'validator must not run'
}}
Import-Module {_ps_quote(_MODULE)} -Force
$identity = [PSCustomObject]@{{
    Username = 'bcb-1234567-abcdef'
    Password = 'secret'
    Domain = '.'
    Sid = 'S-1-5-21-1000-1001-1002-1003'
}}
$message = $null
try {{
    Set-BCBenchWorkspaceAcl `
        -Identity $identity `
        -EntryRoot {_ps_quote(paths["entry"])} `
        -BaselineWorkspace {_ps_quote(paths["baseline"])} `
        -AgentWorkspace {_ps_quote(paths["agent"])} `
        -AgentLogs {_ps_quote(paths["logs"])} `
        -AgentTools {_ps_quote(paths["agent-tools"])} `
        -MountedStaging {_ps_quote(paths["staging"])} `
        -EvaluatorWorkspaces {_ps_quote(paths["evaluators"])} `
        -Evidence {_ps_quote(paths["evidence"])} `
        -ProtectedRoot {_ps_quote(paths["protected"])} `
        -BenchmarkRoot {_ps_quote(paths["benchmark"])} `
        -DatasetPath {_ps_quote(dataset_path)} `
        -ToolRoots @({_ps_quote(paths["tool"])}) `
        -RuntimeExecutablePaths @({_ps_quote(runtime_executable)}) `
        -RuntimeRoots @() `
        -SourceWorkerPath {_ps_quote(source_worker_path)} `
        -WorkerPath {_ps_quote(worker_path)} `
        -WorkerSha256 '{worker_hash}' `
        -IcaclsRunner $runner `
        -AclVerifier {{ }} `
        -AccessValidator $validator | Out-Null
}}
catch {{
    $message = $_.Exception.Message
}}
[PSCustomObject]@{{ calls = $global:calls; validated = $global:validated; message = $message }} | ConvertTo-Json -Compress -Depth 8
"""
    payload = _last_json(_run_pwsh(script))

    assert len(payload["calls"]) == 6
    assert payload["calls"][2:] == [
        [str(paths["benchmark"]), "/remove:g", "*S-1-5-21-1000-1001-1002-1003"],
        [str(paths["benchmark"]), "/remove:d", "*S-1-5-21-1000-1001-1002-1003"],
        [str(paths["entry"]), "/remove:g", "*S-1-5-21-1000-1001-1002-1003"],
        [str(paths["entry"]), "/remove:d", "*S-1-5-21-1000-1001-1002-1003"],
    ]
    assert payload["validated"] is False
    assert "icacls failed with exit code 5" in payload["message"]


def test_remove_agent_acl_uses_exact_sid_for_all_modified_paths() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$global:calls = @()
$global:verification = @()
Import-Module {_ps_quote(_MODULE)} -Force
$transaction = [PSCustomObject]@{{
    Sid = 'S-1-5-21-1000-1001-1002-1003'
    ModifiedPaths = [System.Collections.Generic.List[string]]::new()
    CleanupComplete = $false
}}
$transaction.ModifiedPaths.Add('C:\\external\\tool')
$transaction.ModifiedPaths.Add('C:\\external\\python.exe')
Remove-BCBenchAgentAcl `
    -Transaction $transaction `
    -IcaclsRunner {{
        param([string[]]$Arguments)
        $global:calls += ,@($Arguments)
        return 0
    }} `
    -AclVerifier {{
        param($Parameters)
        $global:verification += $Parameters
    }}
[PSCustomObject]@{{
    calls = $global:calls
    verification = $global:verification
    cleanupComplete = $transaction.CleanupComplete
}} | ConvertTo-Json -Compress -Depth 8
"""
    payload = _last_json(_run_pwsh(script))

    assert payload["calls"] == [
        ["C:\\external\\tool", "/remove:g", "*S-1-5-21-1000-1001-1002-1003"],
        ["C:\\external\\tool", "/remove:d", "*S-1-5-21-1000-1001-1002-1003"],
        ["C:\\external\\python.exe", "/remove:g", "*S-1-5-21-1000-1001-1002-1003"],
        ["C:\\external\\python.exe", "/remove:d", "*S-1-5-21-1000-1001-1002-1003"],
    ]
    assert {(item["Path"], item["Sid"]) for item in payload["verification"]} == {
        ("C:\\external\\tool", "S-1-5-21-1000-1001-1002-1003"),
        ("C:\\external\\python.exe", "S-1-5-21-1000-1001-1002-1003"),
    }
    assert payload["cleanupComplete"] is True


def test_bc_user_uses_real_navserveruser_contract_for_create_existence_removal_and_absence() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$global:newCall = $null
$global:removeCall = $null
$global:users = @([PSCustomObject]@{{ 'User Name' = 'unrelated-user' }})
$global:getUserCalls = 0
$global:getUserParameters = @()
Import-Module {_ps_quote(_MODULE)} -Force
function global:Import-Module {{
    param([string]$Name, [version]$RequiredVersion, [switch]$Force, [switch]$DisableNameChecking)
    if ($Name -ne 'BcContainerHelper' -or [string]$RequiredVersion -ne '6.1.18') {{ throw 'wrong module pin' }}
}}
function global:New-BcContainerBcUser {{
    param([string]$containerName, [PSCredential]$Credential, [string]$PermissionSetId, [bool]$ChangePasswordAtNextLogOn)
    $global:newCall = [PSCustomObject]@{{
        ContainerName = $containerName
        Username = $Credential.UserName
        Password = $Credential.GetNetworkCredential().Password
        PermissionSetId = $PermissionSetId
        ChangePasswordAtNextLogOn = $ChangePasswordAtNextLogOn
    }}
    $global:users += [PSCustomObject]@{{ 'User Name' = $Credential.UserName }}
}}
function global:Invoke-ScriptInBcContainer {{
    param([string]$containerName, [scriptblock]$ScriptBlock, [object[]]$ArgumentList)
    $global:invokedContainer = $containerName
    & $ScriptBlock @ArgumentList
}}
function global:Get-NAVServerInstance {{
    [PSCustomObject]@{{ ServerInstance = 'BC' }}
}}
function global:Get-NAVServerUser {{
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ServerInstance,
        [Parameter(Mandatory = $true)][string]$Tenant
    )
    $global:getUserCalls++
    $global:getUserParameters += [PSCustomObject]@{{
        ServerInstance = $ServerInstance
        Tenant = $Tenant
    }}
    return $global:users
}}
function global:Remove-NAVServerUser {{
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ServerInstance,
        [Parameter(Mandatory = $true)][string]$Tenant,
        [Parameter(Mandatory = $true)][string]$UserName,
        [switch]$Force
    )
    $global:removeCall = [PSCustomObject]@{{
        ServerInstance = $ServerInstance
        Tenant = $Tenant
        Username = $UserName
        Force = [bool]$Force
    }}
    $global:users = @($global:users | Where-Object {{ $_.'User Name' -ne $UserName }})
}}
function global:Remove-BcContainerBcUser {{
    $global:inventedRemoveCalls++
    throw 'invented helper command must not be used'
}}
$global:inventedRemoveCalls = 0
$identity = New-BCBenchAgentBcUser -InstanceId 'entry' -ContainerName 'bc-entry'
$ops = @{{
    InspectContainer = {{
        [PSCustomObject]@{{
            Exists = $true
            Id = 'owned-id'
            InvocationId = 'expected-invocation'
        }}
    }}
}}
Remove-BCBenchAgentBcUser `
    -ContainerName 'bc-entry' `
    -Username $identity.Username `
    -ExpectedContainerId 'owned-id' `
    -ExpectedInvocationId 'expected-invocation' `
    -Operations $ops
[PSCustomObject]@{{
    identity = $identity
    newCall = $global:newCall
    removeCall = $global:removeCall
    invokedContainer = $global:invokedContainer
    getUserCalls = $global:getUserCalls
    getUserParameters = $global:getUserParameters
    remainingUsers = @($global:users | ForEach-Object {{ $_.'User Name' }})
    inventedRemoveCalls = $global:inventedRemoveCalls
}} | ConvertTo-Json -Compress -Depth 6
"""
    payload = _last_json(_run_pwsh(script))

    assert payload["identity"]["Username"].startswith("bca-")
    assert payload["newCall"]["Username"] == payload["identity"]["Username"]
    assert payload["newCall"]["Password"] == payload["identity"]["Password"]
    assert payload["newCall"]["PermissionSetId"] == "SUPER"
    assert payload["newCall"]["ChangePasswordAtNextLogOn"] is False
    assert payload["invokedContainer"] == "owned-id"
    assert payload["removeCall"]["ServerInstance"] == "BC"
    assert payload["removeCall"]["Tenant"] == "default"
    assert payload["removeCall"]["Username"] == payload["identity"]["Username"]
    assert payload["removeCall"]["Force"] is True
    assert payload["getUserCalls"] == 2
    assert payload["getUserParameters"] == [
        {"ServerInstance": "BC", "Tenant": "default"},
        {"ServerInstance": "BC", "Tenant": "default"},
    ]
    assert payload["remainingUsers"] == ["unrelated-user"]
    assert payload["inventedRemoveCalls"] == 0
    assert payload["identity"]["Username"] != "admin"


def test_bc_user_fallback_requires_post_removal_absence() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
function global:Import-Module {{
    param([string]$Name, [version]$RequiredVersion, [switch]$Force, [switch]$DisableNameChecking)
    if ($Name -ne 'BcContainerHelper' -or [string]$RequiredVersion -ne '6.1.18') {{ throw 'wrong module pin' }}
}}
function global:Invoke-ScriptInBcContainer {{
    param([string]$containerName, [scriptblock]$ScriptBlock, [object[]]$ArgumentList)
    & $ScriptBlock @ArgumentList
}}
function global:Get-NAVServerInstance {{
    [PSCustomObject]@{{ ServerInstance = 'BC' }}
}}
function global:Get-NAVServerUser {{
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ServerInstance,
        [Parameter(Mandatory = $true)][string]$Tenant
    )
    [PSCustomObject]@{{ 'User Name' = 'bca-1234567-abcdef' }}
}}
function global:Remove-NAVServerUser {{
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ServerInstance,
        [Parameter(Mandatory = $true)][string]$Tenant,
        [Parameter(Mandatory = $true)][string]$UserName,
        [switch]$Force
    )
}}
$ops = @{{
    InspectContainer = {{
        [PSCustomObject]@{{
            Exists = $true
            Id = 'owned-id'
            InvocationId = 'expected-invocation'
        }}
    }}
}}
$message = $null
try {{
    Remove-BCBenchAgentBcUser `
        -ContainerName 'bc-entry' `
        -Username 'bca-1234567-abcdef' `
        -ExpectedContainerId 'owned-id' `
        -ExpectedInvocationId 'expected-invocation' `
        -Operations $ops
}}
catch {{
    $message = $_.Exception.Message
}}
$message | ConvertTo-Json -Compress
"""
    message = _last_json(_run_pwsh(script))

    assert "still exists after removal" in message


def test_remove_bc_user_rejects_ownership_mismatch_before_container_script() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$global:scriptCalls = 0
Import-Module {_ps_quote(_MODULE)} -Force
function global:Import-Module {{
    param([string]$Name, [version]$RequiredVersion, [switch]$Force, [switch]$DisableNameChecking)
    if ($Name -ne 'BcContainerHelper' -or [string]$RequiredVersion -ne '6.1.18') {{ throw 'wrong module pin' }}
}}
function global:Invoke-ScriptInBcContainer {{
    $global:scriptCalls++
    throw 'container script must not run'
}}
$ops = @{{
    InspectContainer = {{
        [PSCustomObject]@{{
            Exists = $true
            Id = 'replacement-id'
            InvocationId = 'expected-invocation'
        }}
    }}
}}
$message = $null
try {{
    Remove-BCBenchAgentBcUser `
        -ContainerName 'bc-entry' `
        -Username 'bca-1234567-abcdef' `
        -ExpectedContainerId 'owned-id' `
        -ExpectedInvocationId 'expected-invocation' `
        -Operations $ops
}}
catch {{
    $message = $_.Exception.Message
}}
[PSCustomObject]@{{
    message = $message
    scriptCalls = $global:scriptCalls
}} | ConvertTo-Json -Compress
"""
    payload = _last_json(_run_pwsh(script))

    assert "Docker ID changed" in payload["message"]
    assert payload["scriptCalls"] == 0


@pytest.mark.parametrize(
    "failure_mode",
    [
        "ownership_mismatch",
        "bc_remove_failure",
        "bc_absence_failure",
        "remove_failure",
        "post_remove_exists",
        "success",
    ],
)
def test_cleanup_preserves_mounted_roots_until_container_absence_is_verified(tmp_path: Path, failure_mode: str) -> None:
    entry_root = tmp_path / "entry"
    protected_root = tmp_path / "protected"
    quarantine_path = tmp_path / "protected.quarantine.json"
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$global:containerExists = $false
$global:containerId = $null
$global:containerLabel = $null
$global:order = @()
$global:aclCalls = 0
$global:identityRemoveCalls = 0
$global:identityDisableCalls = 0
$ops = @{{
    ResolveEntry = {{ [PSCustomObject]@{{ repo = 'owner/repo'; base_commit = 'abc'; environment_setup_version = '28.0' }} }}
    CloneRepository = {{ param($Context) New-Item -ItemType Directory -Path $Context.BaselineWorkspace -Force | Out-Null }}
    InspectContainer = {{
        param($Context)
        $target = if ($null -ne $Context.PSObject.Properties['InspectionTarget']) {{ $Context.InspectionTarget }} else {{ $Context.ContainerName }}
        $global:order += "inspect:$target"
        [PSCustomObject]@{{
            Exists = $global:containerExists
            Id = $global:containerId
            InvocationId = $global:containerLabel
        }}
    }}
    InspectContainerById = {{
        param($Context)
        $global:order += "inspect-id:$($Context.ContainerId)"
        [PSCustomObject]@{{
            Exists = $global:containerExists -and $global:containerId -eq $Context.ContainerId
            Id = if ($global:containerExists -and $global:containerId -eq $Context.ContainerId) {{ $global:containerId }} else {{ $null }}
            InvocationId = if ($global:containerExists -and $global:containerId -eq $Context.ContainerId) {{ $global:containerLabel }} else {{ $null }}
        }}
    }}
    CreateContainer = {{
        param($Context)
        $global:containerExists = $true
        $global:containerId = 'owned-id'
        $global:containerLabel = $Context.ContainerInvocationId
    }}
    CreateCompiler = {{ }}
    InitializeContainer = {{ }}
    GetCompany = {{ 'CRONUS' }}
    CreateAgentIdentity = {{
        [PSCustomObject]@{{
            Username = 'bcb-1234567-abcdef'
            Password = 'os-secret'
            Domain = '.'
            Sid = 'S-1-5-21-1000-1001-1002-1003'
        }}
    }}
    CreateBcIdentity = {{ [PSCustomObject]@{{ Username = 'bca-1234567-abcdef'; Password = 'bc-secret' }} }}
    ApplyAcl = {{
        param($Context)
        $Context.AclTransaction.ModifiedPaths.Add($Context.EntryRoot)
        if ('{failure_mode}' -eq 'ownership_mismatch') {{
            $global:containerId = 'replacement-id'
            $global:containerLabel = 'replacement-invocation'
        }}
        throw 'forced setup failure'
    }}
    RemoveBcIdentity = {{
        $global:order += 'bc-user'
        if ('{failure_mode}' -eq 'bc_remove_failure') {{ throw 'forced BC user removal failure' }}
    }}
    VerifyBcIdentityAbsent = {{
        $global:order += 'verify-bc-user-absent'
        if ('{failure_mode}' -eq 'bc_absence_failure') {{ throw 'forced BC user absence verification failure' }}
    }}
    RemoveContainer = {{
        param($Context)
        $global:order += "remove-container:$($Context.VerifiedContainerId)"
        if ('{failure_mode}' -eq 'remove_failure') {{ throw 'forced remove failure' }}
        if ('{failure_mode}' -ne 'post_remove_exists') {{
            $global:containerExists = $false
            $global:containerId = $null
            $global:containerLabel = $null
        }}
    }}
    RemoveAcl = {{
        $global:aclCalls++
        $global:order += 'acl'
    }}
    RemoveAgentIdentity = {{
        $global:identityRemoveCalls++
        $global:order += 'remove-local-user'
    }}
    DisableAgentIdentity = {{
        $global:identityDisableCalls++
        $global:order += 'disable-local-user'
    }}
    VerifyAgentIdentityDisabled = {{ }}
}}
$message = $null
try {{
    Invoke-BCBenchBugFixLifecycle `
        -InstanceId 'safe-cleanup' `
        -DatasetPath 'dataset.jsonl' `
        -ContainerName 'bc-owned' `
        -EvaluatorUsername 'admin' `
        -EvaluatorPassword (ConvertTo-SecureString 'evaluator-secret' -AsPlainText -Force) `
        -EntryRoot {_ps_quote(entry_root)} `
        -ProtectedRoot {_ps_quote(protected_root)} `
        -Operations $ops | Out-Null
}}
catch {{
    $message = $_.Exception.Message
}}
[PSCustomObject]@{{
    message = $message
    order = $global:order
    aclCalls = $global:aclCalls
    identityRemoveCalls = $global:identityRemoveCalls
    identityDisableCalls = $global:identityDisableCalls
    entryExists = Test-Path -LiteralPath {_ps_quote(entry_root)}
    protectedExists = Test-Path -LiteralPath {_ps_quote(protected_root)}
    quarantineExists = Test-Path -LiteralPath {_ps_quote(quarantine_path)}
    quarantine = if (Test-Path -LiteralPath {_ps_quote(quarantine_path)}) {{
        Get-Content -LiteralPath {_ps_quote(quarantine_path)} -Raw | ConvertFrom-Json
    }} else {{ $null }}
}} | ConvertTo-Json -Compress -Depth 10
"""
    payload = _last_json(_run_pwsh(script))

    assert "forced setup failure" in payload["message"]
    if failure_mode == "success":
        assert payload["aclCalls"] == 1
        assert payload["identityRemoveCalls"] == 1
        assert payload["identityDisableCalls"] == 0
        assert payload["entryExists"] is False
        assert payload["protectedExists"] is False
        assert payload["quarantineExists"] is False
        assert "inspect-id:owned-id" in payload["order"]
        assert payload["order"].index("verify-bc-user-absent") < payload["order"].index("remove-container:owned-id")
        assert payload["order"].index("remove-container:owned-id") < payload["order"].index("acl")
        assert payload["order"].index("inspect-id:owned-id") < payload["order"].index("acl")
    else:
        assert payload["aclCalls"] == 0
        assert payload["identityRemoveCalls"] == 0
        assert payload["identityDisableCalls"] == 1
        assert payload["entryExists"] is True
        assert payload["protectedExists"] is True
        assert payload["quarantineExists"] is True
        assert Path(payload["quarantine"]["entry_root"]).resolve() == entry_root.resolve()
        assert Path(payload["quarantine"]["protected_root"]).resolve() == protected_root.resolve()
        assert payload["quarantine"]["cleanup_errors"]
        assert str(quarantine_path) in payload["message"]
        if failure_mode == "ownership_mismatch":
            assert not any(item.startswith("remove-container:") for item in payload["order"])
            assert "Refusing container-scoped cleanup" in payload["message"]
        elif failure_mode == "bc_remove_failure":
            assert not any(item.startswith("remove-container:") for item in payload["order"])
            assert "forced BC user removal failure" in payload["message"]
            assert "verify-bc-user-absent" not in payload["order"]
        elif failure_mode == "bc_absence_failure":
            assert not any(item.startswith("remove-container:") for item in payload["order"])
            assert "forced BC user absence verification failure" in payload["message"]
            assert payload["order"].index("bc-user") < payload["order"].index("verify-bc-user-absent")
        elif failure_mode == "remove_failure":
            assert "forced remove failure" in payload["message"]
        else:
            assert "still exists after removal" in payload["message"]
            assert "inspect-id:owned-id" in payload["order"]


def test_setup_orchestrator_writes_outputs_and_cleans_created_resources_on_failure(tmp_path: Path) -> None:
    success_entry = tmp_path / "entry-success"
    success_protected = tmp_path / "protected-success"
    output = tmp_path / "output.txt"
    env_file = tmp_path / "env.txt"
    failure_entry = tmp_path / "entry-failure"
    failure_protected = tmp_path / "protected-failure"
    trace = tmp_path / "cleanup.jsonl"
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$secure = ConvertTo-SecureString 'evaluator-secret' -AsPlainText -Force
$successOps = @{{
    ResolveEntry = {{ [PSCustomObject]@{{ repo = 'owner/repo'; base_commit = 'abc'; environment_setup_version = '28.0' }} }}
    CloneRepository = {{ param($Context) New-Item -ItemType Directory -Path $Context.BaselineWorkspace -Force | Out-Null }}
    InspectContainer = {{
        param($Context)
        $exists = $null -ne $Context.PSObject.Properties['TestContainerPresent'] -and [bool]$Context.TestContainerPresent
        [PSCustomObject]@{{
            Exists = $exists
            Id = if ($exists) {{ 'docker-success' }} else {{ $null }}
            InvocationId = if ($exists) {{ $Context.ContainerInvocationId }} else {{ $null }}
        }}
    }}
    CreateContainer = {{ param($Context) $Context | Add-Member -NotePropertyName TestContainerPresent -NotePropertyValue $true -Force }}
    CreateCompiler = {{ }}
    InitializeContainer = {{ }}
    GetCompany = {{ 'CRONUS' }}
    CreateAgentIdentity = {{ [PSCustomObject]@{{ Username = 'bcb-1234567-abcdef'; Password = 'os-secret'; Domain = '.'; Sid = 'S-1-5-21-1000-1001-1002-1003' }} }}
    CreateBcIdentity = {{ [PSCustomObject]@{{ Username = 'bca-1234567-abcdef'; Password = 'bc-secret' }} }}
    ApplyAcl = {{ [PSCustomObject]@{{ WorkspaceWriteSucceeded = $true }} }}
}}
$env:GITHUB_ACTIONS = 'true'
$successContext = Invoke-BCBenchBugFixLifecycle `
    -InstanceId 'entry-success' `
    -DatasetPath 'dataset.jsonl' `
    -ContainerName 'bc-success' `
    -EvaluatorUsername 'admin' `
    -EvaluatorPassword $secure `
    -EntryRoot {_ps_quote(success_entry)} `
    -ProtectedRoot {_ps_quote(success_protected)} `
    -GithubOutput {_ps_quote(output)} `
    -GithubEnv {_ps_quote(env_file)} `
    -Operations $successOps

$failureOps = @{{
    ResolveEntry = $successOps.ResolveEntry
    CloneRepository = $successOps.CloneRepository
    InspectContainer = $successOps.InspectContainer
    CreateContainer = $successOps.CreateContainer
    CreateCompiler = {{ }}
    InitializeContainer = {{ }}
    GetCompany = {{ 'CRONUS' }}
    CreateAgentIdentity = $successOps.CreateAgentIdentity
    CreateBcIdentity = $successOps.CreateBcIdentity
    ApplyAcl = {{ throw 'acl failure' }}
    RemoveBcIdentity = {{ param($Context) @{{ action = 'bc-user'; username = $Context.AgentBcIdentity.Username }} | ConvertTo-Json -Compress | Add-Content {_ps_quote(trace)} }}
    VerifyBcIdentityAbsent = {{ }}
    RemoveAcl = {{ param($Context) @{{ action = 'acl'; sid = $Context.AgentIdentity.Sid }} | ConvertTo-Json -Compress | Add-Content {_ps_quote(trace)} }}
    RemoveAgentIdentity = {{ param($Context) @{{ action = 'os-user'; username = $Context.AgentIdentity.Username }} | ConvertTo-Json -Compress | Add-Content {_ps_quote(trace)} }}
    RemoveContainer = {{
        param($Context)
        @{{ action = 'container'; name = $Context.ContainerName }} | ConvertTo-Json -Compress | Add-Content {_ps_quote(trace)}
        $Context.TestContainerPresent = $false
    }}
}}
$failed = $false
try {{
    Invoke-BCBenchBugFixLifecycle `
        -InstanceId 'entry-failure' `
        -DatasetPath 'dataset.jsonl' `
        -ContainerName 'bc-failure' `
        -EvaluatorUsername 'admin' `
        -EvaluatorPassword $secure `
        -EntryRoot {_ps_quote(failure_entry)} `
        -ProtectedRoot {_ps_quote(failure_protected)} `
        -Operations $failureOps | Out-Null
}}
catch {{
    $failed = $_.Exception.Message -match 'acl failure'
}}
[PSCustomObject]@{{
    failed = $failed
    output = @(Get-Content {_ps_quote(output)})
    environment = @(Get-Content {_ps_quote(env_file)})
    evaluatorConfig = $successContext.EvaluatorContainerConfig
    agentConfig = $successContext.AgentContainerConfig
    containerPreexisted = $successContext.ContainerPreexisted
    containerSuccessfullyCreated = $successContext.ContainerSuccessfullyCreated
    cleanup = @(Get-Content {_ps_quote(trace)} | ForEach-Object {{ $_ | ConvertFrom-Json }})
    failureEntryExists = Test-Path {_ps_quote(failure_entry)}
    failureProtectedExists = Test-Path {_ps_quote(failure_protected)}
}} | ConvertTo-Json -Compress -Depth 8
"""
    raw_output = _run_pwsh(script)
    payload = _last_json(raw_output)
    output_text = "\n".join(payload["output"])
    env_text = "\n".join(payload["environment"])
    output_values = dict(line.split("=", maxsplit=1) for line in payload["output"])
    evaluator_config = json.loads(output_values["evaluator_container_config"])
    agent_config = json.loads(output_values["agent_container_config"])

    assert "agent_workspace=" in output_text
    assert "agent_tools=" in output_text
    assert "contained_process_worker=" in output_text
    assert "contained_process_worker_sha256=" in output_text
    assert "contained_process_python=" in output_text
    assert "protected_root=" in output_text
    assert "agent_os_username=bcb-1234567-abcdef" in output_text
    assert "agent_os_password=os-secret" in output_text
    assert "agent_bc_password=bc-secret" in output_text
    assert evaluator_config == {
        "name": "bc-success",
        "username": "admin",
        "password": "evaluator-secret",
        "company": "CRONUS",
        "server_url": "http://bc-success",
        "server_instance": "BC",
        "mcp_url": "",
    }
    assert agent_config == {
        "name": "bc-success",
        "username": "bca-1234567-abcdef",
        "password": "bc-secret",
        "company": "CRONUS",
        "server_url": "http://bc-success",
        "server_instance": "BC",
        "mcp_url": "",
    }
    assert payload["evaluatorConfig"] == evaluator_config
    assert payload["agentConfig"] == agent_config
    assert ContainerConfig(**evaluator_config).username == "admin"
    assert ContainerConfig(**agent_config).username == "bca-1234567-abcdef"
    assert evaluator_config["password"] != agent_config["password"]
    assert payload["containerPreexisted"] is False
    assert payload["containerSuccessfullyCreated"] is True
    assert output_values["container_id"] == "docker-success"
    assert output_values["container_observed_invocation_id"] == output_values["container_invocation_id"]
    assert len(output_values["container_invocation_id"]) == 32
    assert set(output_values["container_invocation_id"]) <= set("0123456789abcdef")
    assert "::add-mask::evaluator-secret" in raw_output
    assert "::add-mask::bc-secret" in raw_output
    assert "al_tool_dotnet_version=8.0" in output_text
    assert "BCBENCH_AGENT_WORKSPACE=" in env_text
    assert "BCBENCH_AGENT_TOOLS=" in env_text
    assert "BCBENCH_CONTAINED_PROCESS_WORKER=" in env_text
    assert "BCBENCH_CONTAINED_PROCESS_WORKER_SHA256=" in env_text
    assert "BCBENCH_CONTAINED_PROCESS_PYTHON=" in env_text
    assert "BC_SERVER_PASSWORD=evaluator-secret" in env_text
    assert payload["failed"] is True
    assert {item["action"] for item in payload["cleanup"]} == {"bc-user", "acl", "os-user", "container"}
    assert payload["failureEntryExists"] is False
    assert payload["failureProtectedExists"] is False


@pytest.mark.parametrize(
    ("preexisting", "appearance", "creation_fails", "later_fails", "id_changes", "expected_remove"),
    [
        (True, "none", False, False, False, False),
        (False, "matching", False, True, False, True),
        (False, "matching", True, False, False, True),
        (False, "none", True, False, False, False),
        (False, "mismatched", True, False, False, False),
        (False, "missing", True, False, False, False),
        (False, "matching", True, False, True, False),
    ],
)
def test_concurrent_container_cleanup_requires_matching_label_and_docker_id(
    tmp_path: Path,
    preexisting: bool,
    appearance: str,
    creation_fails: bool,
    later_fails: bool,
    id_changes: bool,
    expected_remove: bool,
) -> None:
    entry_root = tmp_path / "entry"
    protected_root = tmp_path / "protected"
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$global:containerExists = ${str(preexisting).lower()}
$global:containerLabel = if ($global:containerExists) {{ 'another-invocation' }} else {{ $null }}
$global:containerId = if ($global:containerExists) {{ 'preexisting-id' }} else {{ $null }}
$global:inspectCalls = 0
$global:createCalls = 0
$global:removeCalls = 0
$ops = @{{
    ResolveEntry = {{ [PSCustomObject]@{{ repo = 'owner/repo'; base_commit = 'abc'; environment_setup_version = '28.0' }} }}
    CloneRepository = {{ param($Context) New-Item -ItemType Directory -Path $Context.BaselineWorkspace -Force | Out-Null }}
    InspectContainer = {{
        param($Context)
        $global:inspectCalls++
        $id = if (${str(id_changes).lower()} -and $global:inspectCalls -ge 3) {{ 'replacement-id' }} else {{ $global:containerId }}
        [PSCustomObject]@{{
            Exists = $global:containerExists
            Id = $id
            InvocationId = $global:containerLabel
        }}
    }}
    CreateContainer = {{
        param($Context)
        $global:createCalls++
        $global:containerExists = {"$true" if appearance != "none" else "$false"}
        $global:containerId = if ($global:containerExists) {{ 'owned-id' }} else {{ $null }}
        $global:containerLabel = switch ('{appearance}') {{
            'matching' {{ $Context.ContainerInvocationId }}
            'mismatched' {{ 'another-invocation' }}
            default {{ $null }}
        }}
        if (${str(creation_fails).lower()}) {{ throw 'create failure' }}
    }}
    CreateCompiler = {{ if (${str(later_fails).lower()}) {{ throw 'later failure' }} }}
    InitializeContainer = {{ }}
    GetCompany = {{ 'CRONUS' }}
    CreateAgentIdentity = {{ [PSCustomObject]@{{ Username = 'bcb-1234567-abcdef'; Password = 'os-secret'; Domain = '.' }} }}
    CreateBcIdentity = {{ [PSCustomObject]@{{ Username = 'bca-1234567-abcdef'; Password = 'bc-secret' }} }}
    ApplyAcl = {{ [PSCustomObject]@{{ WorkspaceWriteSucceeded = $true }} }}
    RemoveContainer = {{
        $global:removeCalls++
        $global:containerExists = $false
        $global:containerId = $null
        $global:containerLabel = $null
    }}
}}
$message = $null
try {{
    Invoke-BCBenchBugFixLifecycle `
        -InstanceId 'ownership' `
        -DatasetPath 'dataset.jsonl' `
        -ContainerName 'bc-owned' `
        -EvaluatorUsername 'admin' `
        -EvaluatorPassword (ConvertTo-SecureString 'evaluator-secret' -AsPlainText -Force) `
        -EntryRoot {_ps_quote(entry_root)} `
        -ProtectedRoot {_ps_quote(protected_root)} `
        -Operations $ops | Out-Null
}}
catch {{
    $message = $_.Exception.Message
}}
[PSCustomObject]@{{
    message = $message
    createCalls = $global:createCalls
    removeCalls = $global:removeCalls
    containerExists = $global:containerExists
}} | ConvertTo-Json -Compress
"""
    payload = _last_json(_run_pwsh(script))

    assert payload["removeCalls"] == int(expected_remove)
    if preexisting:
        assert payload["createCalls"] == 0
        assert payload["containerExists"] is True
        assert "already exists" in payload["message"]
    elif appearance in {"mismatched", "missing"}:
        assert "missing or different lifecycle invocation label" in payload["message"]
    elif creation_fails:
        assert "create failure" in payload["message"]
    elif later_fails:
        assert "later failure" in payload["message"]
    if id_changes:
        assert "Docker ID changed" in payload["message"]


@pytest.mark.parametrize(
    ("replacement", "acl_fails", "expected_order", "expected_bc_calls", "expected_container_calls"),
    [
        (
            False,
            False,
            [
                "verify-bc",
                "bc-user:owned-id",
                "verify-bc-user-absent",
                "container:owned-id",
                "verify-container-name",
                "verify-container-id",
                "acl",
                "os-user",
            ],
            1,
            1,
        ),
        (
            True,
            False,
            ["verify-bc", "disable-local-user", "verify-local-user-disabled"],
            0,
            0,
        ),
        (
            False,
            True,
            [
                "verify-bc",
                "bc-user:owned-id",
                "verify-bc-user-absent",
                "container:owned-id",
                "verify-container-name",
                "verify-container-id",
                "acl",
                "disable-local-user",
                "verify-local-user-disabled",
            ],
            1,
            1,
        ),
    ],
)
def test_cleanup_is_transactional_and_ownership_verified_per_container_operation(
    tmp_path: Path,
    replacement: bool,
    acl_fails: bool,
    expected_order: list[str],
    expected_bc_calls: int,
    expected_container_calls: int,
) -> None:
    entry_root = tmp_path / "entry"
    protected_root = tmp_path / "protected"
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$global:containerExists = $false
$global:containerId = $null
$global:containerLabel = $null
$global:inspectCalls = 0
$global:bcCalls = 0
$global:containerCalls = 0
$global:osCalls = 0
$global:order = @()
$ops = @{{
    ResolveEntry = {{ [PSCustomObject]@{{ repo = 'owner/repo'; base_commit = 'abc'; environment_setup_version = '28.0' }} }}
    CloneRepository = {{ param($Context) New-Item -ItemType Directory -Path $Context.BaselineWorkspace -Force | Out-Null }}
    InspectContainer = {{
        param($Context)
        $global:inspectCalls++
        if ($global:inspectCalls -gt 2) {{
            $phase = if ($global:inspectCalls -eq 3) {{ 'verify-bc' }} else {{ 'verify-container-name' }}
            $global:order += $phase
        }}
        $id = if (${str(replacement).lower()} -and $global:inspectCalls -gt 2) {{ 'replacement-id' }} else {{ $global:containerId }}
        [PSCustomObject]@{{
            Exists = $global:containerExists
            Id = $id
            InvocationId = $global:containerLabel
        }}
    }}
    InspectContainerById = {{
        param($Context)
        $global:order += 'verify-container-id'
        [PSCustomObject]@{{
            Exists = $global:containerExists -and $global:containerId -eq $Context.ContainerId
            Id = if ($global:containerExists -and $global:containerId -eq $Context.ContainerId) {{ $global:containerId }} else {{ $null }}
            InvocationId = if ($global:containerExists -and $global:containerId -eq $Context.ContainerId) {{ $global:containerLabel }} else {{ $null }}
        }}
    }}
    CreateContainer = {{
        param($Context)
        $global:containerExists = $true
        $global:containerId = 'owned-id'
        $global:containerLabel = $Context.ContainerInvocationId
    }}
    CreateCompiler = {{ }}
    InitializeContainer = {{ }}
    GetCompany = {{ 'CRONUS' }}
    CreateAgentIdentity = {{
        [PSCustomObject]@{{
            Username = 'bcb-1234567-abcdef'
            Password = 'os-secret'
            Domain = '.'
            Sid = 'S-1-5-21-1000-1001-1002-1003'
        }}
    }}
    CreateBcIdentity = {{ [PSCustomObject]@{{ Username = 'bca-1234567-abcdef'; Password = 'bc-secret' }} }}
    ApplyAcl = {{
        param($Context)
        $Context.AclTransaction.ModifiedPaths.Add($Context.PythonBaseExecutable)
        [PSCustomObject]@{{ WorkspaceWriteSucceeded = $true; AclTransaction = $Context.AclTransaction }}
    }}
    RemoveBcIdentity = {{
        param($Context)
        $global:bcCalls++
        $global:order += "bc-user:$($Context.VerifiedContainerId)"
    }}
    VerifyBcIdentityAbsent = {{
        $global:order += 'verify-bc-user-absent'
    }}
    RemoveAcl = {{
        param($Context)
        $global:order += 'acl'
        if (${str(acl_fails).lower()}) {{ throw 'forced ACL cleanup failure' }}
        $Context.AclTransaction.CleanupComplete = $true
    }}
    RemoveAgentIdentity = {{
        $global:osCalls++
        $global:order += 'os-user'
    }}
    DisableAgentIdentity = {{
        $global:order += 'disable-local-user'
    }}
    VerifyAgentIdentityDisabled = {{
        $global:order += 'verify-local-user-disabled'
    }}
    RemoveContainer = {{
        param($Context)
        $global:containerCalls++
        $global:order += "container:$($Context.VerifiedContainerId)"
        $global:containerExists = $false
        $global:containerId = $null
        $global:containerLabel = $null
    }}
}}
$message = $null
try {{
    Invoke-BCBenchBugFixLifecycle `
        -InstanceId 'transactional-cleanup' `
        -DatasetPath 'dataset.jsonl' `
        -ContainerName 'bc-owned' `
        -EvaluatorUsername 'admin' `
        -EvaluatorPassword (ConvertTo-SecureString 'evaluator-secret' -AsPlainText -Force) `
        -EntryRoot {_ps_quote(entry_root)} `
        -ProtectedRoot {_ps_quote(protected_root)} `
        -GithubOutput {_ps_quote(protected_root)} `
        -Operations $ops | Out-Null
}}
catch {{
    $message = $_.Exception.Message
}}
[PSCustomObject]@{{
    message = $message
    order = $global:order
    bcCalls = $global:bcCalls
    containerCalls = $global:containerCalls
    osCalls = $global:osCalls
}} | ConvertTo-Json -Compress -Depth 8
"""
    payload = _last_json(_run_pwsh(script))

    assert payload["order"] == expected_order
    assert payload["bcCalls"] == expected_bc_calls
    assert payload["containerCalls"] == expected_container_calls
    if replacement:
        assert "Docker ID changed" in payload["message"]
    elif acl_fails:
        assert "forced ACL cleanup failure" in payload["message"]
        assert "retained for quarantine" in payload["message"]
        assert payload["osCalls"] == 0
    else:
        assert payload["osCalls"] == 1


@pytest.mark.parametrize("fallback_failure", ["none", "disable", "verification"])
def test_local_user_removal_failure_immediately_disables_and_verifies_exact_identity(tmp_path: Path, fallback_failure: str) -> None:
    entry_root = tmp_path / "entry"
    protected_root = tmp_path / "protected"
    quarantine_path = tmp_path / "protected.quarantine.json"
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$global:containerExists = $false
$global:containerId = $null
$global:containerLabel = $null
$global:order = @()
$ops = @{{
    ResolveEntry = {{ [PSCustomObject]@{{ repo = 'owner/repo'; base_commit = 'abc'; environment_setup_version = '28.0' }} }}
    CloneRepository = {{ param($Context) New-Item -ItemType Directory -Path $Context.BaselineWorkspace -Force | Out-Null }}
    InspectContainer = {{
        [PSCustomObject]@{{
            Exists = $global:containerExists
            Id = $global:containerId
            InvocationId = $global:containerLabel
        }}
    }}
    InspectContainerById = {{
        [PSCustomObject]@{{
            Exists = $global:containerExists
            Id = $global:containerId
            InvocationId = $global:containerLabel
        }}
    }}
    CreateContainer = {{
        param($Context)
        $global:containerExists = $true
        $global:containerId = 'owned-id'
        $global:containerLabel = $Context.ContainerInvocationId
    }}
    CreateCompiler = {{ }}
    InitializeContainer = {{ }}
    GetCompany = {{ 'CRONUS' }}
    CreateAgentIdentity = {{
        [PSCustomObject]@{{
            Username = 'bcb-1234567-abcdef'
            Password = 'os-secret'
            Domain = '.'
            Sid = 'S-1-5-21-1000-1001-1002-1003'
        }}
    }}
    CreateBcIdentity = {{ [PSCustomObject]@{{ Username = 'bca-1234567-abcdef'; Password = 'bc-secret' }} }}
    ApplyAcl = {{
        param($Context)
        $Context.AclTransaction.ModifiedPaths.Add($Context.EntryRoot)
        throw 'forced setup failure'
    }}
    RemoveBcIdentity = {{ $global:order += 'remove-bc-user' }}
    VerifyBcIdentityAbsent = {{ $global:order += 'verify-bc-user-absent' }}
    RemoveContainer = {{
        $global:order += 'remove-container'
        $global:containerExists = $false
        $global:containerId = $null
        $global:containerLabel = $null
    }}
    RemoveAcl = {{
        param($Context)
        $global:order += 'remove-acl'
        $Context.AclTransaction.CleanupComplete = $true
    }}
    RemoveAgentIdentity = {{
        param($Context)
        $global:order += "remove-local-user:$($Context.AgentIdentity.Username)"
        throw 'forced local user removal failure'
    }}
    DisableAgentIdentity = {{
        param($Context)
        $global:order += "disable-local-user:$($Context.AgentIdentity.Username)"
        if ('{fallback_failure}' -eq 'disable') {{ throw 'forced local user disable failure' }}
    }}
    VerifyAgentIdentityDisabled = {{
        param($Context)
        $global:order += "verify-local-user-disabled:$($Context.AgentIdentity.Username)"
        if ('{fallback_failure}' -eq 'verification') {{ throw 'local user remains enabled' }}
    }}
}}
$message = $null
try {{
    Invoke-BCBenchBugFixLifecycle `
        -InstanceId 'identity-fallback' `
        -DatasetPath 'dataset.jsonl' `
        -ContainerName 'bc-owned' `
        -EvaluatorUsername 'admin' `
        -EvaluatorPassword (ConvertTo-SecureString 'evaluator-secret' -AsPlainText -Force) `
        -EntryRoot {_ps_quote(entry_root)} `
        -ProtectedRoot {_ps_quote(protected_root)} `
        -Operations $ops | Out-Null
}}
catch {{
    $message = $_.Exception.Message
}}
[PSCustomObject]@{{
    message = $message
    order = $global:order
    entryExists = Test-Path -LiteralPath {_ps_quote(entry_root)}
    protectedExists = Test-Path -LiteralPath {_ps_quote(protected_root)}
    quarantineExists = Test-Path -LiteralPath {_ps_quote(quarantine_path)}
    quarantine = if (Test-Path -LiteralPath {_ps_quote(quarantine_path)}) {{
        Get-Content -LiteralPath {_ps_quote(quarantine_path)} -Raw | ConvertFrom-Json
    }} else {{ $null }}
}} | ConvertTo-Json -Compress -Depth 10
"""
    payload = _last_json(_run_pwsh(script))

    exact_username = "bcb-1234567-abcdef"
    remove_action = f"remove-local-user:{exact_username}"
    disable_action = f"disable-local-user:{exact_username}"
    verify_action = f"verify-local-user-disabled:{exact_username}"
    assert payload["order"][:7] == [
        "remove-bc-user",
        "verify-bc-user-absent",
        "remove-container",
        "remove-acl",
        remove_action,
        disable_action,
        *([] if fallback_failure == "disable" else [verify_action]),
    ]
    assert "forced local user removal failure" in payload["message"]
    assert payload["quarantineExists"] is True
    assert payload["quarantine"]["local_username"] == exact_username
    assert payload["quarantine"]["local_sid"] == "S-1-5-21-1000-1001-1002-1003"
    assert any("forced local user removal failure" in error for error in payload["quarantine"]["cleanup_errors"])
    if fallback_failure == "none":
        assert payload["entryExists"] is False
        assert payload["protectedExists"] is False
    else:
        assert payload["entryExists"] is True
        assert payload["protectedExists"] is True
        expected_error = "forced local user disable failure" if fallback_failure == "disable" else "local user remains enabled"
        assert expected_error in payload["message"]


@pytest.mark.e2e
def test_disposable_bc_container_user_fallback_lifecycle() -> None:
    if os.environ.get("BCBENCH_RUN_BC_USER_E2E") != "1":
        pytest.skip("set BCBENCH_RUN_BC_USER_E2E=1 to run the disposable BC user lifecycle e2e test")
    container_name = os.environ.get("BCBENCH_E2E_CONTAINER_NAME", "").strip()
    if not container_name:
        pytest.skip("requires BCBENCH_E2E_CONTAINER_NAME naming a disposable BC container")
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("requires evaluator Docker daemon access and the Docker CLI")
    docker_access = subprocess.run(
        [docker, "version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if docker_access.returncode != 0:
        pytest.skip("requires evaluator Docker daemon access and the Docker CLI")
    container_exists = subprocess.run(
        [docker, "container", "inspect", container_name],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if container_exists.returncode != 0:
        pytest.skip(f"requires disposable BC container '{container_name}' to exist")
    inspect_payload = json.loads(container_exists.stdout)[0]
    container_id = inspect_payload["Id"]
    invocation_id = inspect_payload.get("Config", {}).get("Labels", {}).get("bcbench.lifecycle.invocation")
    if not invocation_id:
        pytest.skip("requires a lifecycle-owned disposable BC container with an invocation label")
    if os.environ.get("BCBENCH_E2E_OWNS_CONTAINER") == "1":
        setup_output = os.environ.get("BCBENCH_E2E_SETUP_OUTPUT", "").strip()
        if not setup_output:
            pytest.skip("requires BCBENCH_E2E_SETUP_OUTPUT when the e2e test owns the container")
        setup_output_path = Path(setup_output)
        if not setup_output_path.is_file():
            pytest.skip("requires an existing BCBENCH_E2E_SETUP_OUTPUT file when the e2e test owns the container")
        destinations = {mount["Destination"] for mount in inspect_payload["Mounts"]}
        assert {
            r"C:\bcbench\baseline",
            r"C:\bcbench\agent",
            r"C:\bcbench\evaluators",
            r"C:\bcbench\staging",
        } <= destinations
        setup_values = dict(line.split("=", maxsplit=1) for line in setup_output_path.read_text(encoding="utf-8-sig").splitlines() if "=" in line)
        for output_name in ("evaluator_container_config", "agent_container_config"):
            config = json.loads(setup_values[output_name])
            assert set(config) == {
                "name",
                "username",
                "password",
                "company",
                "server_url",
                "server_instance",
                "mcp_url",
            }
            assert config["name"] == container_name
    helper_check = subprocess.run(
        [
            "pwsh",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Import-Module BcContainerHelper -RequiredVersion 6.1.18 -ErrorAction Stop",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if helper_check.returncode != 0:
        pytest.skip("requires BcContainerHelper 6.1.18")

    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$identity = $null
function Test-AgentUserExists {{
    param([string]$ContainerName, [string]$Username)
    return [bool](Invoke-ScriptInBcContainer -containerName $ContainerName -ScriptBlock {{
        param([string]$Username)
        $serverInstance = (Get-NAVServerInstance | Select-Object -First 1).ServerInstance
        return $null -ne (@(Get-NAVServerUser -ServerInstance $serverInstance -Tenant 'default') | Where-Object {{ $_.'User Name' -eq $Username }})
    }} -ArgumentList $Username)
}}
$PSDefaultParameterValues['Remove-BCBenchAgentBcUser:ExpectedContainerId'] = {_ps_quote(container_id)}
$PSDefaultParameterValues['Remove-BCBenchAgentBcUser:ExpectedInvocationId'] = {_ps_quote(invocation_id)}
$removeAgentBcUserCommand = Get-Command Remove-BCBenchAgentBcUser -Module BugFixLifecycle
function Remove-BCBenchAgentBcUser {{
    param(
        [string]$ContainerName,
        [string]$Username,
        [Alias('Password')][string]$IgnoredCredential
    )
    & $removeAgentBcUserCommand `
        -ContainerName $ContainerName `
        -Username $Username `
        -ExpectedContainerId {_ps_quote(container_id)} `
        -ExpectedInvocationId {_ps_quote(invocation_id)}
}}
try {{
    $identity = New-BCBenchAgentBcUser -InstanceId 'e2e-{secrets.token_hex(3)}' -ContainerName {_ps_quote(container_name)}
    $existsAfterCreate = Test-AgentUserExists -ContainerName {_ps_quote(container_name)} -Username $identity.Username
    Remove-BCBenchAgentBcUser -ContainerName {_ps_quote(container_name)} -Username $identity.Username******
    $absentAfterRemove = -not (Test-AgentUserExists -ContainerName {_ps_quote(container_name)} -Username $identity.Username)
    [PSCustomObject]@{{
        username = $identity.Username
        existsAfterCreate = $existsAfterCreate
        absentAfterRemove = $absentAfterRemove
    }} | ConvertTo-Json -Compress
}}
finally {{
    if ($null -ne $identity -and (Test-AgentUserExists -ContainerName {_ps_quote(container_name)} -Username $identity.Username)) {{
        Remove-BCBenchAgentBcUser -ContainerName {_ps_quote(container_name)} -Username $identity.Username******
    }}
}}
"""
    payload = _last_json(_run_pwsh(script))

    assert payload["username"].startswith("bca-")
    assert payload["existsAfterCreate"] is True
    assert payload["absentAfterRemove"] is True


@pytest.mark.integration
@pytest.mark.parametrize("force_probe_failure", [False, True])
def test_elevated_disposable_identity_access_cleans_exact_user(tmp_path: Path, force_probe_failure: bool) -> None:
    if shutil.which("docker") is None:
        pytest.skip("requires Docker CLI")
    elevated = _run_pwsh("([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)")
    if elevated.lower() != "true":
        pytest.skip("requires an elevated Windows process")

    entry_root = tmp_path / "entry"
    protected_root = tmp_path / "protected"
    baseline = entry_root / "baseline-workspace"
    workspace = entry_root / "agent-workspace"
    logs = entry_root / "agent-logs"
    staging = entry_root / "mounted-staging"
    evaluators = entry_root / "evaluator-workspaces"
    evidence = entry_root / "evidence"
    tool_parent = tmp_path / "tool-parent"
    tool_root = tool_parent / "tool-root"
    benchmark_parent = tmp_path / "benchmark-parent"
    benchmark_root = benchmark_parent / "benchmark"
    dataset_path = benchmark_root / "dataset" / "bcbench.jsonl"
    evaluator_source = benchmark_root / "src" / "bcbench" / "evaluate"
    docs = benchmark_root / "docs"
    source_worker = benchmark_root / "src" / "bcbench" / "agent" / "shared" / "contained_process_worker.py"
    for path in (baseline, workspace, logs, staging, evaluators, evidence, tool_root, protected_root, dataset_path.parent, evaluator_source, docs, source_worker.parent):
        path.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text("{}\n", encoding="utf-8")
    (evaluator_source / "__init__.py").write_text("", encoding="utf-8")
    (docs / "readme.txt").write_text("restricted", encoding="utf-8")
    source_worker.write_bytes((_ROOT / "src" / "bcbench" / "agent" / "shared" / "contained_process_worker.py").read_bytes())
    for path, grants in (
        (benchmark_parent, ("*S-1-5-32-545:(OI)(CI)RX",)),
        (
            tool_parent,
            (
                "*S-1-5-32-545:(OI)(CI)M",
                "*S-1-5-11:(OI)(CI)M",
            ),
        ),
    ):
        inherited_acl = subprocess.run(
            ["icacls.exe", str(path), "/grant", *grants],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert inherited_acl.returncode == 0, inherited_acl.stdout + inherited_acl.stderr
    secret_path = protected_root / "secret.txt"
    secret_path.write_text("secret", encoding="utf-8")
    instance_id = f"integration-{secrets.token_hex(3)}"
    access_validator = "{ throw 'forced probe failure' }" if force_probe_failure else "$null"
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$runtime = Resolve-BCBenchPythonRuntime -PythonExecutable {_ps_quote(sys.executable)}
$identity = $null
$username = $null
$access = $null
$aclTransaction = $null
$probeError = $null
$agentAclRemains = $false
$benchmarkDenyApplied = $false
$inheritedUsersAllowPresent = $false
$agentToolsInheritanceProtected = $false
$workerInheritanceProtected = $false
$agentWorkerWriteGrantPresent = $false
$readExecuteDenyPaths = @()
$inheritedModifySids = @()
$baseAclPreserved = $false
$userPresentBeforeAclCleanup = $false
$userPresentAfterAclCleanup = $false
try {{
    $identity = New-BCBenchAgentIdentity -InstanceId {_ps_quote(instance_id)}
    $username = $identity.Username
    $aclTransaction = [PSCustomObject]@{{
        Sid = $identity.Sid
        ModifiedPaths = [System.Collections.Generic.List[string]]::new()
        CleanupComplete = $false
    }}
    $tools = New-BCBenchAgentTools `
        -EntryRoot {_ps_quote(entry_root)} `
        -BenchmarkRoot {_ps_quote(benchmark_root)} `
        -SourceWorkerPath {_ps_quote(source_worker)}
    $parameters = @{{
        Identity = $identity
        EntryRoot = {_ps_quote(entry_root)}
        BaselineWorkspace = {_ps_quote(baseline)}
        AgentWorkspace = {_ps_quote(workspace)}
        AgentLogs = {_ps_quote(logs)}
        AgentTools = $tools.AgentTools
        MountedStaging = {_ps_quote(staging)}
        EvaluatorWorkspaces = {_ps_quote(evaluators)}
        Evidence = {_ps_quote(evidence)}
        ProtectedRoot = {_ps_quote(protected_root)}
        BenchmarkRoot = {_ps_quote(benchmark_root)}
        DatasetPath = {_ps_quote(dataset_path)}
        ToolRoots = @({_ps_quote(tool_root)})
        RuntimeExecutablePaths = @($runtime.BaseExecutable)
        RuntimeRoots = @($runtime.BasePrefix)
        SourceWorkerPath = {_ps_quote(source_worker)}
        WorkerPath = $tools.WorkerPath
        WorkerSha256 = $tools.WorkerSha256
        AclTransaction = $aclTransaction
    }}
    $validator = {access_validator}
    if ($null -ne $validator) {{ $parameters.AccessValidator = $validator }}
    $access = Set-BCBenchWorkspaceAcl @parameters
    $benchmarkAcl = Get-Acl -LiteralPath {_ps_quote(benchmark_root)}
    $benchmarkDenyApplied = [bool]($benchmarkAcl.Access | Where-Object {{
        $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Deny -and
        $_.IdentityReference.Value -match [regex]::Escape($username)
    }})
    $inheritedUsersAllowPresent = [bool]($benchmarkAcl.Access | Where-Object {{
        if ($_.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or -not $_.IsInherited) {{ return $false }}
        try {{ return $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq 'S-1-5-32-545' }}
        catch {{ return $false }}
    }})
    $agentSid = ([Security.Principal.NTAccount]::new([Environment]::MachineName, $username)).Translate([Security.Principal.SecurityIdentifier]).Value
    $agentToolsAcl = Get-Acl -LiteralPath $tools.AgentTools
    $workerAcl = Get-Acl -LiteralPath $tools.WorkerPath
    $agentToolsInheritanceProtected = $agentToolsAcl.AreAccessRulesProtected
    $workerInheritanceProtected = $workerAcl.AreAccessRulesProtected
    $writeRights = [Security.AccessControl.FileSystemRights]::WriteData `
        -bor [Security.AccessControl.FileSystemRights]::AppendData `
        -bor [Security.AccessControl.FileSystemRights]::WriteAttributes `
        -bor [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes `
        -bor [Security.AccessControl.FileSystemRights]::Delete `
        -bor [Security.AccessControl.FileSystemRights]::ChangePermissions `
        -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
    $agentWorkerWriteGrantPresent = [bool]($workerAcl.Access | Where-Object {{
        if ($_.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) {{ return $false }}
        try {{ $ruleSid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }}
        catch {{ return $false }}
        return $ruleSid -eq $agentSid -and ($_.FileSystemRights -band $writeRights) -ne 0
    }})
    $denyPaths = @(
        $tools.AgentTools,
        $tools.WorkerPath,
        {_ps_quote(tool_root)},
        $runtime.BasePrefix,
        $runtime.BaseExecutable
    )
    $readExecuteDenyPaths = @($denyPaths | Where-Object {{
        $path = $_
        $acl = Get-Acl -LiteralPath $path
        [bool]($acl.Access | Where-Object {{
            if ($_.AccessControlType -ne [Security.AccessControl.AccessControlType]::Deny -or $_.IsInherited) {{ return $false }}
            try {{ $ruleSid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }}
            catch {{ $ruleSid = $_.IdentityReference.Value }}
            return $ruleSid -eq $agentSid -and ($_.FileSystemRights -band $writeRights) -eq $writeRights
        }})
    }})
    $toolAcl = Get-Acl -LiteralPath {_ps_quote(tool_root)}
    $inheritedModifySids = @($toolAcl.Access | Where-Object {{
        $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
        $_.IsInherited -and
        ($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::Modify) -eq [Security.AccessControl.FileSystemRights]::Modify
    }} | ForEach-Object {{
        try {{ $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }}
        catch {{ $_.IdentityReference.Value }}
    }})
}}
catch {{
    $probeError = $_.Exception.Message
}}
finally {{
    if ($null -ne $username) {{
        $aclCleanupSucceeded = $false
        try {{
            $userPresentBeforeAclCleanup = $null -ne (Get-LocalUser -Name $username -ErrorAction SilentlyContinue)
            Remove-BCBenchAgentAcl -Transaction $aclTransaction
            $userPresentAfterAclCleanup = $null -ne (Get-LocalUser -Name $username -ErrorAction SilentlyContinue)
            foreach ($path in $aclTransaction.ModifiedPaths | Select-Object -Unique) {{
                if (-not (Test-Path -LiteralPath $path)) {{ continue }}
                $acl = Get-Acl -LiteralPath $path
                if ($acl.Access | Where-Object {{
                    try {{ $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq $identity.Sid }}
                    catch {{ $_.IdentityReference.Value -eq $identity.Sid }}
                }}) {{
                    $agentAclRemains = $true
                }}
            }}
            $evaluatorSid = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
            $baseAclPreserved = @({_ps_quote(workspace)}, {_ps_quote(protected_root)}, $tools.AgentTools, $tools.WorkerPath) |
                ForEach-Object {{
                    $acl = Get-Acl -LiteralPath $_
                    $aclSids = @($acl.Access | ForEach-Object {{
                        try {{ $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }}
                        catch {{ $_.IdentityReference.Value }}
                    }})
                    $aclSids -contains $evaluatorSid -and $aclSids -contains 'S-1-5-18'
                }} |
                Where-Object {{ -not $_ }} |
                Measure-Object |
                Select-Object -ExpandProperty Count
            $baseAclPreserved = $baseAclPreserved -eq 0
            if (-not $agentAclRemains) {{
                $aclCleanupSucceeded = $true
            }}
        }}
        finally {{
            if ($aclCleanupSucceeded) {{
                Remove-BCBenchAgentIdentity -Username $username
            }}
        }}
    }}
}}
[PSCustomObject]@{{
    username = $username
    access = $access
    probeError = $probeError
    agentAclRemains = $agentAclRemains
    benchmarkDenyApplied = $benchmarkDenyApplied
    inheritedUsersAllowPresent = $inheritedUsersAllowPresent
    agentToolsInheritanceProtected = $agentToolsInheritanceProtected
    workerInheritanceProtected = $workerInheritanceProtected
    agentWorkerWriteGrantPresent = $agentWorkerWriteGrantPresent
    readExecuteDenyPaths = $readExecuteDenyPaths
    inheritedModifySids = $inheritedModifySids
    trackedPathCount = $aclTransaction.ModifiedPaths.Count
    baseAclPreserved = $baseAclPreserved
    userPresentBeforeAclCleanup = $userPresentBeforeAclCleanup
    userPresentAfterAclCleanup = $userPresentAfterAclCleanup
    userRemains = if ($null -eq $username) {{ $false }} else {{ $null -ne (Get-LocalUser -Name $username -ErrorAction SilentlyContinue) }}
}} | ConvertTo-Json -Compress -Depth 8
"""
    payload = _last_json(_run_pwsh(script))

    assert payload["username"].startswith("bcb-")
    assert payload["agentAclRemains"] is False
    assert payload["trackedPathCount"] == 14
    assert payload["baseAclPreserved"] is True
    assert payload["userPresentBeforeAclCleanup"] is True
    assert payload["userPresentAfterAclCleanup"] is True
    assert payload["userRemains"] is False
    if force_probe_failure:
        assert "forced probe failure" in payload["probeError"]
    else:
        assert payload["probeError"] is None
        assert payload["benchmarkDenyApplied"] is True
        assert payload["inheritedUsersAllowPresent"] is True
        assert payload["agentToolsInheritanceProtected"] is False
        assert payload["workerInheritanceProtected"] is False
        assert payload["agentWorkerWriteGrantPresent"] is False
        assert len(payload["readExecuteDenyPaths"]) == 5
        assert {"S-1-5-32-545", "S-1-5-11"} <= set(payload["inheritedModifySids"])
        assert payload["access"]["WorkspaceWriteSucceeded"] is True
        assert payload["access"]["ProtectedReadDenied"] is True
        assert payload["access"]["ProtectedWriteDenied"] is True
        assert payload["access"]["BenchmarkWriteDenied"] is True
        assert payload["access"]["DatasetReadDenied"] is True
        assert payload["access"]["EvaluatorSourceReadDenied"] is True
        assert payload["access"]["DocsReadDenied"] is True
        assert payload["access"]["AgentToolsWriteDenied"] is True
        assert payload["access"]["ReadExecuteDirectoryReadSucceeded"] is True
        assert payload["access"]["ReadExecuteDirectoryCreateDenied"] is True
        assert payload["access"]["ReadExecuteDirectoryWriteDenied"] is True
        assert payload["access"]["ReadExecuteDirectoryDeleteDenied"] is True
        assert payload["access"]["ReadExecuteFileReadSucceeded"] is True
        assert payload["access"]["ReadExecuteFileModifyDenied"] is True
        assert payload["access"]["RuntimeExecutableExecutionSucceeded"] is True
        assert payload["access"]["MountedStagingCreateDenied"] is True
        assert payload["access"]["MountedStagingWriteDenied"] is True
        assert payload["access"]["MountedStagingDeleteDenied"] is True
        assert payload["access"]["OutputParentCreateDenied"] is True
        assert payload["access"]["OutputParentWriteDenied"] is True
        assert payload["access"]["OutputParentDeleteDenied"] is True
        assert payload["access"]["OutputFileOpenDenied"] is True
        assert payload["access"]["OutputHandleCaptureSucceeded"] is True
        assert {Path(item["Path"]).resolve() for item in payload["access"]["ReadExecuteDirectoryResults"]} == {
            (entry_root / "agent-tools").resolve(),
            tool_root.resolve(),
            Path(sys.base_prefix).resolve(),
        }
        assert all(item["ReadSucceeded"] and item["CreateDenied"] and item["WriteDenied"] and item["DeleteDenied"] for item in payload["access"]["ReadExecuteDirectoryResults"])
        assert {Path(item["Path"]).resolve() for item in payload["access"]["ReadExecuteFileResults"]} == {
            (entry_root / "agent-tools" / "contained_process_worker.py").resolve(),
            Path(getattr(sys, "_base_executable", sys.executable)).resolve(),
        }
        assert all(item["ReadSucceeded"] and item["ModifyDenied"] for item in payload["access"]["ReadExecuteFileResults"])
        assert len(payload["access"]["RuntimeExecutableResults"]) == 1
        assert payload["access"]["RuntimeExecutableResults"][0]["ExecutionSucceeded"] is True
        assert payload["access"]["DockerCliDenied"] is True
        assert payload["access"]["DockerPipeDenied"] is True
        assert payload["access"]["ProcessId"] > 0
