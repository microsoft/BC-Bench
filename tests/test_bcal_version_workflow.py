import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "bcal-evaluation.yml"
INSTALL_ACTION = ROOT / ".github" / "actions" / "install-bcal" / "action.yml"
INSTALL_SCRIPT = ROOT / "scripts" / "Install-BCalTool.ps1"
PWSH = shutil.which("pwsh")
PACKAGE_ID = "Example.BCal"
FEED_URL = "https://example.invalid/nuget/index.json"


def _workflow() -> dict[Any, Any]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _step(workflow: dict[Any, Any], name: str) -> dict[str, Any]:
    return next(step for step in workflow["jobs"]["evaluate-with-bcal"]["steps"] if step.get("name") == name)


def test_bcal_package_selection_encodes_valid_channel_and_version_modes() -> None:
    workflow = _workflow()
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    selection = inputs["bcal-package-selection"]
    version = inputs["bcal-version"]

    assert selection["type"] == "choice"
    assert selection["default"] == "official-latest"
    assert selection["options"] == ["official-latest", "official-pinned", "experiment-pinned"]
    assert selection["required"] is False
    assert version["type"] == "string"
    assert version["default"] == ""
    assert version["required"] is False
    assert "BCAL_VERSION_MODE" not in workflow["env"]
    assert workflow["env"]["BCAL_REQUESTED_VERSION"] == "${{ inputs.bcal-version }}"
    assert workflow["jobs"]["validate-bcal-package"]["outputs"]["version-mode"] == "${{ steps.resolve.outputs.version-mode }}"


def test_bcal_installed_version_output_flows_to_evaluation_metadata() -> None:
    workflow = _workflow()
    install = _step(workflow, "Install bcal CLI from internal feed")
    evaluate = _step(workflow, "Run BCal for entry ${{ matrix.entry }}")
    action = yaml.safe_load(INSTALL_ACTION.read_text(encoding="utf-8"))
    action_install = next(step for step in action["runs"]["steps"] if step.get("id") == "install")

    assert install["id"] == "install-bcal"
    assert install["uses"] == "$/.github/actions/install-bcal"
    assert action["outputs"]["version"]["value"] == "${{ steps.install.outputs.version }}"
    assert ".\\scripts\\Install-BCalTool.ps1" in action_install["run"]
    assert '-VersionMode "$env:BCAL_VERSION_MODE"' in action_install["run"]
    assert '-Version "$env:BCAL_REQUESTED_VERSION"' in action_install["run"]
    assert '-PackageId "$env:BCAL_PACKAGE_ID"' in action_install["run"]
    assert '-FeedUrl "$env:BCAL_FEED_URL"' in action_install["run"]
    assert "${{ inputs." not in action_install["run"]
    assert evaluate["env"]["BCAL_PACKAGE_VERSION"] == "${{ steps.install-bcal.outputs.version }}"
    assert evaluate["env"]["BCAL_PACKAGE_CHANNEL"] == "${{ needs.validate-bcal-package.outputs.source }}"
    assert evaluate["env"]["BCAL_PACKAGE_BRANCH"] == "${{ needs.validate-bcal-package.outputs.branch }}"
    assert "[string]::IsNullOrWhiteSpace($env:BCAL_PACKAGE_VERSION)" in evaluate["run"]
    assert evaluate["run"].index("BCAL_PACKAGE_VERSION") < evaluate["run"].index("bcbench evaluate bcal")


def test_bcal_matrix_resolves_versions_per_job_and_preserves_feed_authentication() -> None:
    workflow = _workflow()
    matrix = workflow["jobs"]["evaluate-with-bcal"]
    install = _step(workflow, "Install bcal CLI from internal feed")
    action = yaml.safe_load(INSTALL_ACTION.read_text(encoding="utf-8"))
    login, credential_provider, action_install = action["runs"]["steps"]

    assert "resolve-bcal-version" not in workflow["jobs"]
    assert set(matrix["needs"]) == {"validate-bcal-package", "get-entries"}
    assert len([step for step in matrix["steps"] if step.get("uses") == "$/.github/actions/install-bcal"]) == 1
    assert install["with"] == {
        "client-id": "${{ secrets.AZURE_CLIENT_ID }}",
        "tenant-id": "${{ secrets.AZURE_TENANT_ID }}",
        "package-id": "${{ secrets.BCAL_PACKAGE_ID }}",
        "feed-url": "${{ needs.validate-bcal-package.outputs.source == 'experiment' && secrets.BCAL_TEST_FEED_URL || secrets.BCAL_FEED_URL }}",
        "version-mode": "${{ needs.validate-bcal-package.outputs.version-mode }}",
        "version": "${{ env.BCAL_REQUESTED_VERSION }}",
    }
    assert action["runs"]["using"] == "composite"
    assert action["inputs"]["version-mode"]["required"] is True
    assert login["uses"] == "azure/login@a641126d1b8aa4d1fa005f4f92df94a3a4c4c906"
    assert login["with"] == {
        "client-id": "${{ inputs.client-id }}",
        "tenant-id": "${{ inputs.tenant-id }}",
        "allow-no-subscriptions": True,
    }
    assert "dotnet tool install --global Microsoft.Artifacts.CredentialProvider.NuGet.Tool" in credential_provider["run"]
    assert "az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798" in action_install["run"]
    assert matrix["environment"] == {"name": "ado-read", "deployment": False}
    assert matrix["permissions"] == {"contents": "read", "id-token": "write"}


def _install_bcal_tool(
    *,
    mode: str = "latest-prerelease",
    version: str = "",
    installed_packages: list[dict[str, object]] | None = None,
    list_output: str | None = None,
    install_exit_codes: list[int] | None = None,
    list_exit_code: int = 0,
) -> dict[str, Any]:
    assert PWSH is not None
    packages = installed_packages if installed_packages is not None else [{"packageId": PACKAGE_ID, "version": "1.2.3-preview.4", "commands": ["bcal"]}]
    case = {
        "package_id": PACKAGE_ID,
        "feed_url": FEED_URL,
        "mode": mode,
        "version": version,
        "list_output": list_output if list_output is not None else json.dumps({"version": 1, "data": packages}),
        "install_exit_codes": install_exit_codes or [0],
        "list_exit_code": list_exit_code,
    }
    result = subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            r"""
            $ErrorActionPreference = "Stop"
            $case = $env:BCAL_INSTALL_TEST_CASE | ConvertFrom-Json -AsHashtable
            $global:BcalTestCalls = [System.Collections.Generic.List[object]]::new()
            $global:BcalTestOutputs = [System.Collections.Generic.List[string]]::new()
            $global:BcalTestSleeps = [System.Collections.Generic.List[int]]::new()
            $global:BcalTestInstallCount = 0
            function dotnet {
                $global:BcalTestCalls.Add(@($args))
                if ($args[0] -eq "tool" -and $args[1] -eq "install") {
                    if ($global:BcalTestInstallCount -ge $case.install_exit_codes.Count) {
                        throw "Unexpected extra installation attempt."
                    }
                    $global:LASTEXITCODE = $case.install_exit_codes[$global:BcalTestInstallCount]
                    $global:BcalTestInstallCount++
                    return
                }
                if ($args[0] -eq "tool" -and $args[1] -eq "list") {
                    $global:LASTEXITCODE = $case.list_exit_code
                    $case.list_output
                    return
                }
                throw "Unexpected dotnet command."
            }
            function Add-Content {
                param([string]$LiteralPath, [string]$Value, [string]$Encoding)
                if ($LiteralPath -ne "bcal-install-test-output") { throw "Unexpected output path." }
                $global:BcalTestOutputs.Add($Value)
            }
            function Start-Sleep {
                param([int]$Seconds)
                $global:BcalTestSleeps.Add($Seconds)
            }
            $env:GITHUB_OUTPUT = "bcal-install-test-output"
            $failure = ""
            try {
                & $env:BCAL_INSTALL_TEST_SCRIPT `
                    -PackageId $case.package_id -FeedUrl $case.feed_url `
                    -VersionMode $case.mode -Version $case.version | Out-Null
            }
            catch {
                $failure = $_.Exception.Message
            }
            @{
                calls = $global:BcalTestCalls.ToArray()
                outputs = $global:BcalTestOutputs.ToArray()
                sleeps = $global:BcalTestSleeps.ToArray()
                error = $failure
            } | ConvertTo-Json -Compress -Depth 6
            """,
        ],
        env={
            **os.environ,
            "PATH": "",
            "BCAL_INSTALL_TEST_CASE": json.dumps(case),
            "BCAL_INSTALL_TEST_SCRIPT": str(INSTALL_SCRIPT),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
@pytest.mark.parametrize(
    ("mode", "version", "actual_version"),
    [
        ("latest-prerelease", "", "7.8.9-preview.10"),
        ("latest-prerelease", " \t", "18.0.38.47039-beta"),
        ("pinned", "7.8.9", "7.8.9"),
        ("pinned", "7.8.9-preview.10", "7.8.9-preview.10"),
        ("pinned", "7.8.9.1", "7.8.9.1"),
        ("pinned", "7.8.9+build.10", "7.8.9+build.10"),
    ],
)
def test_bcal_install_uses_selected_mode_and_records_actual_version(mode: str, version: str, actual_version: str) -> None:
    result = _install_bcal_tool(
        mode=mode,
        version=version,
        installed_packages=[{"packageId": PACKAGE_ID, "version": actual_version, "commands": ["bcal"]}],
    )
    version_arguments = ["--version", version] if mode == "pinned" else ["--prerelease"]

    assert result["error"] == ""
    assert result["calls"] == [
        ["tool", "install", "--global", PACKAGE_ID, *version_arguments, "--source", FEED_URL],
        ["tool", "list", PACKAGE_ID, "--global", "--format", "json"],
    ]
    assert result["outputs"] == [f"version={actual_version}"]
    assert result["sleeps"] == []


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
@pytest.mark.parametrize(
    ("mode", "version"),
    [
        ("latest-prerelease", "1.2.3"),
        ("latest-prerelease", "1.*"),
        ("pinned", ""),
        ("pinned", " \t"),
        ("pinned", "*"),
        ("pinned", "1.2.*"),
        ("pinned", "[1.2.3]"),
        ("pinned", "[1.2.3,2.0.0)"),
        ("pinned", "latest"),
        ("pinned", "1.2.3\n"),
        ("pinned", "1.2.3 --prerelease"),
        ("pinned", "$(Write-Output injected)"),
        ("pinned", "1.2.3; Write-Output injected"),
        ("unknown-mode", ""),
    ],
)
def test_bcal_invalid_version_selection_fails_before_dotnet(mode: str, version: str) -> None:
    result = _install_bcal_tool(mode=mode, version=version)

    assert result["error"]
    assert result["calls"] == []
    assert result["outputs"] == []
    assert result["sleeps"] == []


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
def test_bcal_installed_version_lookup_is_case_insensitive_and_package_scoped() -> None:
    result = _install_bcal_tool(
        installed_packages=[
            {"packageId": "Credential.Provider", "version": "99.0.0", "commands": ["credential-provider"]},
            {"packageId": f"{PACKAGE_ID}.Extra", "version": "98.0.0", "commands": ["other"]},
            {"packageId": PACKAGE_ID.upper(), "version": "2.3.4-preview.5", "commands": ["bcal", "bcal-shell"]},
        ]
    )

    assert result["error"] == ""
    assert result["outputs"] == ["version=2.3.4-preview.5"]


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
@pytest.mark.parametrize(
    ("packages", "error"),
    [
        ([], "found 0"),
        ([{"packageId": f"{PACKAGE_ID}.Extra", "version": "1.2.3"}], "found 0"),
        ([{"packageId": PACKAGE_ID, "version": "1.2.3"}, {"packageId": PACKAGE_ID.lower(), "version": "1.2.3"}], "found 2"),
        ([{"packageId": PACKAGE_ID, "version": "unknown"}], "Invalid installed-version data"),
        ([{"packageId": PACKAGE_ID, "version": ""}], "Invalid installed-version data"),
        ([{"packageId": PACKAGE_ID, "version": None}], "Invalid installed-version data"),
        ([{"packageId": PACKAGE_ID, "version": 1}], "Invalid installed-version data"),
        ([{"packageId": PACKAGE_ID}], "Invalid installed-version data"),
    ],
)
def test_bcal_missing_ambiguous_or_malformed_installed_version_fails_without_metadata(packages: list[dict[str, object]], error: str) -> None:
    result = _install_bcal_tool(installed_packages=packages)

    assert error in result["error"]
    assert result["outputs"] == []


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
@pytest.mark.parametrize(
    "list_output",
    ["", "not JSON", "null", "[]", "{}", '{"version":1}', '{"version":1,"data":null}', '{"version":1,"data":{}}', '{"version":2,"data":[]}'],
)
def test_bcal_invalid_tool_list_json_fails_without_metadata(list_output: str) -> None:
    result = _install_bcal_tool(list_output=list_output)

    assert "dotnet tool list returned" in result["error"]
    assert result["outputs"] == []


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
def test_bcal_installed_version_must_match_requested_pin() -> None:
    result = _install_bcal_tool(mode="pinned", version="1.2.3", installed_packages=[{"packageId": PACKAGE_ID, "version": "1.2.4", "commands": ["bcal"]}])

    assert "does not match requested version '1.2.3'" in result["error"]
    assert result["outputs"] == []


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
def test_bcal_transient_install_failure_retries_same_exact_pin() -> None:
    result = _install_bcal_tool(mode="pinned", version="1.2.3-preview.4", install_exit_codes=[1, 1, 0])

    assert result["error"] == ""
    assert result["calls"][:3] == [["tool", "install", "--global", PACKAGE_ID, "--version", "1.2.3-preview.4", "--source", FEED_URL]] * 3
    assert result["calls"][3] == ["tool", "list", PACKAGE_ID, "--global", "--format", "json"]
    assert result["outputs"] == ["version=1.2.3-preview.4"]
    assert result["sleeps"] == [20, 20]


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
@pytest.mark.parametrize(
    ("install_exit_codes", "list_exit_code", "message", "call_count"),
    [([1, 1, 1], 0, "install failed after 3 attempts", 3), ([0], 1, "dotnet tool list failed", 2)],
)
def test_bcal_install_or_list_failure_never_publishes_version_metadata(install_exit_codes: list[int], list_exit_code: int, message: str, call_count: int) -> None:
    result = _install_bcal_tool(install_exit_codes=install_exit_codes, list_exit_code=list_exit_code)

    assert message in result["error"]
    assert len(result["calls"]) == call_count
    assert result["outputs"] == []
