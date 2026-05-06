using module .\DatasetEntry.psm1
using module .\BCBenchUtils.psm1

<#
.SYNOPSIS
    Downloads the BC artifact for an NL2AL dataset entry into the BCContainerHelper cache.
.DESCRIPTION
    Looks up the BC version for the given InstanceId in the NL2AL dataset and downloads the matching BC artifact via BcContainerHelper.
    The artifact (including Microsoft_Application_*.app) lands in BCContainerHelper's default cache (using default path: C:\bcartifacts.cache),
    where the NL2AL pipeline looks it up at evaluation time.
.PARAMETER InstanceId
    The NL2AL dataset instance_id to resolve the BC version for.
.PARAMETER DatasetPath
    Path to the NL2AL dataset (.jsonl). Defaults to dataset/nl2al.jsonl in the repo.
.PARAMETER Country
    BC artifact country (default: w1).
.EXAMPLE
    .\scripts\Download-ApplicationApp.ps1 -InstanceId nl2al__job-budget-report-1
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

Import-Module BcContainerHelper -Force -DisableNameChecking

[string] $artifactUrl = Get-BCArtifactUrl -version $version -country $Country -select 'Latest'
if (-not $artifactUrl) { throw "No BC artifact URL resolved for version $version ($Country)" }
Write-Log "Downloading artifact: $artifactUrl" -Level Info

$paths = Download-Artifacts -artifactUrl $artifactUrl -includePlatform

$appFile = Get-ChildItem -Path $paths -Recurse -File -Filter "Microsoft_Application_$version.*.app" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $appFile) { throw "Microsoft_Application_$version.*.app not found in artifacts: $($paths -join ', ')" }

Write-Log "Artifact ready at $($appFile.FullName)" -Level Success
