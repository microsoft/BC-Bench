import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bcbench.agent.shared.contained_process import WindowsIdentity
from bcbench.types import ContainerConfig

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell lifecycle")

_ROOT = Path(__file__).parents[1]
_MODULE = _ROOT / "scripts" / "BugFixLifecycle.psm1"
_SETUP = _ROOT / "scripts" / "Setup-BugFixLifecycle.ps1"
_EXPECTED_EXPORTS = {
    "New-BCBenchAgentIdentity",
    "Remove-BCBenchAgentIdentity",
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
        "AlMcp",
        "BcMcp",
    } <= metadata.keys()
    assert any('ValidateSet("bug-fix")' in attribute for attribute in metadata["Category"])
    assert "Import-Module BcContainerHelper -RequiredVersion 6.1.18" in source
    assert "New-BCContainerSync" in source


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
    [PSCustomObject]@{{ Name = $Name }}
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
    assert len(payload["identity"]["Username"]) <= 20
    assert payload["identity"]["Password"]
    assert payload["identity"]["Domain"]
    assert payload["groups"] == ["S-1-5-32-545"]
    assert "S-1-5-32-544" not in payload["groups"]
    assert "docker-users" not in payload["groups"]


def test_workspace_acl_uses_exact_checked_icacls_commands_and_runs_access_validator(tmp_path: Path) -> None:
    entry_root = tmp_path / "entry"
    paths = {
        name: entry_root / name
        for name in (
            "baseline",
            "agent",
            "logs",
            "staging",
            "evaluators",
            "evidence",
        )
    }
    paths["entry"] = entry_root
    paths["protected"] = tmp_path / "protected"
    paths["tool"] = tmp_path / "tool"
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
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
        DockerCliDenied = $true
        DockerPipeDenied = $true
        ProcessId = 1234
        WorkspaceProbePath = 'probe'
        ProtectedProbePath = 'secret'
    }}
}}
Import-Module {_ps_quote(_MODULE)} -Force
$identity = [PSCustomObject]@{{ Username = 'bcb-1234567-abcdef'; Password = 'secret'; Domain = '.' }}
$result = Set-BCBenchWorkspaceAcl `
    -Identity $identity `
    -EntryRoot {_ps_quote(paths["entry"])} `
    -BaselineWorkspace {_ps_quote(paths["baseline"])} `
    -AgentWorkspace {_ps_quote(paths["agent"])} `
    -AgentLogs {_ps_quote(paths["logs"])} `
    -MountedStaging {_ps_quote(paths["staging"])} `
    -EvaluatorWorkspaces {_ps_quote(paths["evaluators"])} `
    -Evidence {_ps_quote(paths["evidence"])} `
    -ProtectedRoot {_ps_quote(paths["protected"])} `
    -ToolRoots @({_ps_quote(paths["tool"])}) `
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
    expected_calls.append([str(paths["tool"]), "/grant:r", f"{agent}:(OI)(CI)RX"])

    assert payload["calls"] == expected_calls
    assert len(payload["verificationCalls"]) == 9
    assert all("*" not in call[0] and "?" not in call[0] for call in payload["calls"])
    assert payload["result"]["ProcessId"] == 1234


def test_workspace_acl_stops_on_icacls_failure(tmp_path: Path) -> None:
    entry_root = tmp_path / "entry"
    paths = {
        name: entry_root / name
        for name in (
            "baseline",
            "agent",
            "logs",
            "staging",
            "evaluators",
            "evidence",
        )
    }
    paths["entry"] = entry_root
    paths["protected"] = tmp_path / "protected"
    paths["tool"] = tmp_path / "tool"
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
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
$identity = [PSCustomObject]@{{ Username = 'bcb-1234567-abcdef'; Password = 'secret'; Domain = '.' }}
$message = $null
try {{
    Set-BCBenchWorkspaceAcl `
        -Identity $identity `
        -EntryRoot {_ps_quote(paths["entry"])} `
        -BaselineWorkspace {_ps_quote(paths["baseline"])} `
        -AgentWorkspace {_ps_quote(paths["agent"])} `
        -AgentLogs {_ps_quote(paths["logs"])} `
        -MountedStaging {_ps_quote(paths["staging"])} `
        -EvaluatorWorkspaces {_ps_quote(paths["evaluators"])} `
        -Evidence {_ps_quote(paths["evidence"])} `
        -ProtectedRoot {_ps_quote(paths["protected"])} `
        -ToolRoots @({_ps_quote(paths["tool"])}) `
        -IcaclsRunner $runner `
        -AccessValidator $validator | Out-Null
}}
catch {{
    $message = $_.Exception.Message
}}
[PSCustomObject]@{{ calls = $global:calls; validated = $global:validated; message = $message }} | ConvertTo-Json -Compress -Depth 8
"""
    payload = _last_json(_run_pwsh(script))

    assert len(payload["calls"]) == 2
    assert payload["validated"] is False
    assert "icacls failed with exit code 5" in payload["message"]


def test_bc_user_uses_distinct_credential_super_and_pinned_helper_fallback_cleanup() -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$global:newCall = $null
$global:removeCall = $null
$global:userPresent = $true
$global:getUserCalls = 0
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
    param([string]$ServerInstance, [string]$Tenant, [string]$UserName)
    $global:getUserCalls++
    if ($global:userPresent) {{ return [PSCustomObject]@{{ UserName = $UserName }} }}
    return $null
}}
function global:Remove-NAVServerUser {{
    param([string]$ServerInstance, [string]$Tenant, [string]$UserName, [switch]$Force)
    $global:removeCall = [PSCustomObject]@{{
        ServerInstance = $ServerInstance
        Tenant = $Tenant
        Username = $UserName
        Force = [bool]$Force
    }}
    $global:userPresent = $false
}}
$identity = New-BCBenchAgentBcUser -InstanceId 'entry' -ContainerName 'bc-entry'
Remove-BCBenchAgentBcUser -ContainerName 'bc-entry' -Username $identity.Username -Password $identity.Password
[PSCustomObject]@{{
    identity = $identity
    newCall = $global:newCall
    removeCall = $global:removeCall
    invokedContainer = $global:invokedContainer
    getUserCalls = $global:getUserCalls
    userPresent = $global:userPresent
}} | ConvertTo-Json -Compress -Depth 6
"""
    payload = _last_json(_run_pwsh(script))

    assert payload["identity"]["Username"].startswith("bca-")
    assert payload["newCall"]["Username"] == payload["identity"]["Username"]
    assert payload["newCall"]["Password"] == payload["identity"]["Password"]
    assert payload["newCall"]["PermissionSetId"] == "SUPER"
    assert payload["newCall"]["ChangePasswordAtNextLogOn"] is False
    assert payload["invokedContainer"] == "bc-entry"
    assert payload["removeCall"]["ServerInstance"] == "BC"
    assert payload["removeCall"]["Tenant"] == "default"
    assert payload["removeCall"]["Username"] == payload["identity"]["Username"]
    assert payload["removeCall"]["Force"] is True
    assert payload["getUserCalls"] == 2
    assert payload["userPresent"] is False
    assert payload["identity"]["Username"] != "admin"


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
    TestContainerExists = {{ $false }}
    CreateContainer = {{ }}
    CreateCompiler = {{ }}
    InitializeContainer = {{ }}
    GetCompany = {{ 'CRONUS' }}
    CreateAgentIdentity = {{ [PSCustomObject]@{{ Username = 'bcb-1234567-abcdef'; Password = 'os-secret'; Domain = '.' }} }}
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
    TestContainerExists = {{ $false }}
    CreateContainer = {{ }}
    CreateCompiler = {{ }}
    InitializeContainer = {{ }}
    GetCompany = {{ 'CRONUS' }}
    CreateAgentIdentity = $successOps.CreateAgentIdentity
    CreateBcIdentity = $successOps.CreateBcIdentity
    ApplyAcl = {{ throw 'acl failure' }}
    RemoveBcIdentity = {{ param($Context) @{{ action = 'bc-user'; username = $Context.AgentBcIdentity.Username }} | ConvertTo-Json -Compress | Add-Content {_ps_quote(trace)} }}
    RemoveAgentIdentity = {{ param($Context) @{{ action = 'os-user'; username = $Context.AgentIdentity.Username }} | ConvertTo-Json -Compress | Add-Content {_ps_quote(trace)} }}
    RemoveContainer = {{ param($Context) @{{ action = 'container'; name = $Context.ContainerName }} | ConvertTo-Json -Compress | Add-Content {_ps_quote(trace)} }}
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
    assert "::add-mask::evaluator-secret" in raw_output
    assert "::add-mask::bc-secret" in raw_output
    assert "al_tool_dotnet_version=8.0" in output_text
    assert "BCBENCH_AGENT_WORKSPACE=" in env_text
    assert "BC_SERVER_PASSWORD=evaluator-secret" in env_text
    assert payload["failed"] is True
    assert {item["action"] for item in payload["cleanup"]} == {"bc-user", "os-user", "container"}
    assert payload["failureEntryExists"] is False
    assert payload["failureProtectedExists"] is False


@pytest.mark.parametrize(
    ("preexisting", "creation_appears", "creation_fails", "later_fails", "expected_remove"),
    [
        (True, False, False, False, False),
        (False, True, False, True, True),
        (False, True, True, False, True),
        (False, False, True, False, False),
    ],
)
def test_container_cleanup_only_removes_containers_owned_by_invocation(
    tmp_path: Path,
    preexisting: bool,
    creation_appears: bool,
    creation_fails: bool,
    later_fails: bool,
    expected_remove: bool,
) -> None:
    entry_root = tmp_path / "entry"
    protected_root = tmp_path / "protected"
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$global:containerExists = ${str(preexisting).lower()}
$global:createCalls = 0
$global:removeCalls = 0
$ops = @{{
    ResolveEntry = {{ [PSCustomObject]@{{ repo = 'owner/repo'; base_commit = 'abc'; environment_setup_version = '28.0' }} }}
    CloneRepository = {{ param($Context) New-Item -ItemType Directory -Path $Context.BaselineWorkspace -Force | Out-Null }}
    TestContainerExists = {{ return $global:containerExists }}
    CreateContainer = {{
        $global:createCalls++
        $global:containerExists = ${str(creation_appears).lower()}
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
    elif creation_fails:
        assert "create failure" in payload["message"]
    elif later_fails:
        assert "later failure" in payload["message"]


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
    if os.environ.get("BCBENCH_E2E_OWNS_CONTAINER") == "1":
        setup_output = os.environ.get("BCBENCH_E2E_SETUP_OUTPUT", "").strip()
        if not setup_output:
            pytest.skip("requires BCBENCH_E2E_SETUP_OUTPUT when the e2e test owns the container")
        setup_output_path = Path(setup_output)
        if not setup_output_path.is_file():
            pytest.skip("requires an existing BCBENCH_E2E_SETUP_OUTPUT file when the e2e test owns the container")
        inspect_payload = json.loads(container_exists.stdout)[0]
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
        return $null -ne (Get-NAVServerUser -ServerInstance $serverInstance -Tenant 'default' -UserName $Username)
    }} -ArgumentList $Username)
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


@pytest.mark.e2e
def test_elevated_disposable_identity_access_uses_contained_process(tmp_path: Path) -> None:
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
    tool_root = Path(sys.executable).parent
    for path in (baseline, workspace, logs, staging, evaluators, evidence, protected_root):
        path.mkdir(parents=True, exist_ok=True)
    secret_path = protected_root / "secret.txt"
    secret_path.write_text("secret", encoding="utf-8")
    identity: WindowsIdentity | None = None
    try:
        script = f"""
$ErrorActionPreference = 'Stop'
Import-Module {_ps_quote(_MODULE)} -Force
$identity = New-BCBenchAgentIdentity -InstanceId 'e2e-{secrets.token_hex(3)}'
$access = Set-BCBenchWorkspaceAcl `
    -Identity $identity `
    -EntryRoot {_ps_quote(entry_root)} `
    -BaselineWorkspace {_ps_quote(baseline)} `
    -AgentWorkspace {_ps_quote(workspace)} `
    -AgentLogs {_ps_quote(logs)} `
    -MountedStaging {_ps_quote(staging)} `
    -EvaluatorWorkspaces {_ps_quote(evaluators)} `
    -Evidence {_ps_quote(evidence)} `
    -ProtectedRoot {_ps_quote(protected_root)} `
    -ToolRoots @({_ps_quote(tool_root)})
[PSCustomObject]@{{ identity = $identity; access = $access }} | ConvertTo-Json -Compress -Depth 8
"""
        payload = _last_json(_run_pwsh(script))
        identity = WindowsIdentity(
            payload["identity"]["Username"],
            payload["identity"]["Password"],
            payload["identity"]["Domain"],
        )

        assert payload["access"]["WorkspaceWriteSucceeded"] is True
        assert payload["access"]["ProtectedReadDenied"] is True
        assert payload["access"]["ProtectedWriteDenied"] is True
        assert payload["access"]["DockerCliDenied"] is True
        assert payload["access"]["DockerPipeDenied"] is True
        assert payload["access"]["ProcessId"] > 0
    finally:
        if identity is not None:
            _run_pwsh(f"Import-Module {_ps_quote(_MODULE)} -Force; Remove-BCBenchAgentIdentity -Username {_ps_quote(identity.username)}")
