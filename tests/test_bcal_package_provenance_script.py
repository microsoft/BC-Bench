import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PWSH = shutil.which("pwsh")
SCRIPT = Path(__file__).parents[1] / "scripts" / "Resolve-BCalPackageProvenance.ps1"


def _resolve_package(*, source_ref="refs/heads/feature/test", source_chain=None, repository="bic/BC-DeveloperExperience"):
    assert PWSH is not None
    case = {
        "source_chain": [] if source_chain is None else source_chain,
        "source_ref": source_ref,
        "repository": repository,
    }
    result = subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            r"""
            $ErrorActionPreference = "Stop"
            $case = $env:BCAL_PROVENANCE_TEST_CASE | ConvertFrom-Json -AsHashtable
            $global:BcalOutputs = [System.Collections.Generic.List[string]]::new()
            function az {
                $global:LASTEXITCODE = 0
                "test-token"
            }
            function Invoke-RestMethod {
                param([string]$Uri, [hashtable]$Headers, [string]$Method)
                if ($Uri -match '/feeds\?') {
                    return @{ value = @(@{ name = "ExperimentFeed"; id = "feed-id" }) }
                }
                if ($Uri -match '/packages\?') {
                    return @{ value = @(@{ name = "Microsoft.BusinessCentral.BCal.CLI"; id = "package-id" }) }
                }
                if ($Uri -match '/versions\?') {
                    return @{
                        value = @(
                            @{
                                id = "version-id"
                                version = "30.0.43.223-beta"
                                sourceChain = $case.source_chain
                                publishDate = "2026-10-01T10:35:28Z"
                            }
                        )
                    }
                }
                if ($Uri -match '/provenance\?') {
                    return @{
                        provenance = @{
                            provenanceSource = "InternalBuild"
                            data = @{
                                "Build.Repository.Id" = $case.repository
                                "Build.SourceBranch" = $case.source_ref
                            }
                        }
                    }
                }
                throw "Unexpected URI: $Uri"
            }
            function Add-Content {
                param([string]$LiteralPath, [string]$Value, [string]$Encoding)
                if ($LiteralPath -ne "bcal-provenance-test-output") { throw "Unexpected output path." }
                $global:BcalOutputs.Add($Value)
            }
            $env:GITHUB_OUTPUT = "bcal-provenance-test-output"
            $failure = ""
            try {
                & $env:BCAL_PROVENANCE_TEST_SCRIPT `
                    -PackageId "Microsoft.BusinessCentral.BCal.CLI" `
                    -Version "30.0.43.223-beta" `
                    -TestFeedUrl "https://example.pkgs.visualstudio.com/_packaging/ExperimentFeed@Local/nuget/v3/index.json" | Out-Null
            }
            catch {
                $failure = $_.Exception.Message
            }
            @{ outputs = $global:BcalOutputs.ToArray(); error = $failure } | ConvertTo-Json -Compress -Depth 8
            """,
        ],
        env={
            **os.environ,
            "PATH": "",
            "BCAL_PROVENANCE_TEST_CASE": json.dumps(case),
            "BCAL_PROVENANCE_TEST_SCRIPT": str(SCRIPT),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.splitlines()[-1])


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package provenance")
def test_experimental_package_branch_is_verified_and_published():
    result = _resolve_package()

    assert result["error"] == ""
    assert result["outputs"] == ["branch=feature/test"]


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package provenance")
def test_pr_package_uses_stable_pr_label():
    result = _resolve_package(source_ref="refs/pull/123/merge")

    assert result["error"] == ""
    assert result["outputs"] == ["branch=pr/123"]


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package provenance")
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source_ref": "refs/heads/master"}, "not an experimental branch"),
        ({"source_chain": ["official-upstream"]}, "not published directly"),
        ({"repository": "other/repository"}, "not 'bic/BC-DeveloperExperience'"),
    ],
)
def test_unverified_branch_package_is_rejected(overrides, message):
    result = _resolve_package(**overrides)

    assert message in result["error"]
    assert result["outputs"] == []
