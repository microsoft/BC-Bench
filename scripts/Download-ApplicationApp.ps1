using module .\DatasetEntry.psm1
using module .\BCBenchUtils.psm1

<#
.SYNOPSIS
    Downloads the BC Application.app symbol file for an NL2AL dataset entry.
.DESCRIPTION
    Looks up the BC version for the given InstanceId in the NL2AL dataset, downloads the
    matching BC artifact via BcContainerHelper, and copies Microsoft_Application_*.app
    into <repo_root>/.bcbench-cache/, preserving the original filename.
.PARAMETER InstanceId
    The NL2AL dataset instance_id to resolve the BC version for.
.PARAMETER DatasetPath
    Path to the NL2AL dataset (.jsonl). Defaults to dataset/nl2al.jsonl in the repo.
.PARAMETER Country
    BC artifact country (default: w1).
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$InstanceId,

    [Parameter(Mandatory = $false)]
    [string]$DatasetPath = (Get-BCBenchDatasetPath -DatasetName "nl2al.jsonl"),

    [Parameter(Mandatory = $false)]
    [string]$Country = "W1"
)

$ErrorActionPreference = 'Stop'

[DatasetEntry[]] $entries = Get-DatasetEntries -DatasetPath $DatasetPath -InstanceId $InstanceId
if (-not $entries -or $entries.Count -eq 0) {
    throw "Entry '$InstanceId' not found in $DatasetPath"
}
[string] $version = $entries[0].environment_setup_version
Write-Log "Resolved BC version $version for InstanceId $InstanceId" -Level Info

[string] $destinationDir = Join-Path (Split-Path $PSScriptRoot -Parent) ".bcbench-cache"

Import-Module BcContainerHelper -Force -DisableNameChecking

[string] $artifactUrl = Get-BCArtifactUrl -version $version -country $Country -select 'Latest'
if (-not $artifactUrl) { throw "No BC artifact URL resolved for version $version ($Country)" }
Write-Log "Downloading artifact: $artifactUrl" -Level Info

$paths = Download-Artifacts -artifactUrl $artifactUrl -includePlatform

$appFile = Get-ChildItem -Path $paths -Recurse -File -Filter 'Microsoft_Application_*.app' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $appFile) { throw "Microsoft_Application_*.app not found in artifacts: $($paths -join ', ')" }

New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
$destinationPath = Join-Path $destinationDir $appFile.Name
Copy-Item -Path $appFile.FullName -Destination $destinationPath -Force

Write-Log "Copied $($appFile.Name) to $destinationPath" -Level Success
