using module ..\packages\bcbench-core\src\bcbench_core\powershell\BCBenchUtils.psm1
using module .\BenchmarkUtils.psm1

<#
.SYNOPSIS
    Downloads the BC artifact for a dataset entry into the BCContainerHelper cache.
.DESCRIPTION
    Looks up the BC version for the given InstanceId in the dataset and downloads the matching BC artifact via BcContainerHelper.
    The artifact (including all *.app symbol packages) lands in BCContainerHelper's default cache (using default path: C:\bcartifacts.cache),
    where the pipeline copies them at evaluation time.
.PARAMETER InstanceId
    The dataset instance_id to resolve the BC version for.
.PARAMETER Category
    The dataset category used to resolve the dataset path (via Get-BCBenchDatasetPath).
.PARAMETER DatasetPath
    Optional override for the dataset (.jsonl) path. Defaults to the category-specific path via Get-BCBenchDatasetPath.
.PARAMETER Version
    BC version to download directly (e.g. from `bcbench dataset version`), skipping the dataset lookup.
.PARAMETER Country
    BC artifact country (default: w1).
.EXAMPLE
    .\scripts\Download-BCSymbols.ps1 -Category bug-fix -InstanceId bug-fix__job-budget-report-1
.EXAMPLE
    .\scripts\Download-BCSymbols.ps1 -Version 28.0
#>
[CmdletBinding(DefaultParameterSetName = 'ByEntry')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'ByEntry')]
    [string]$InstanceId,

    [Parameter(Mandatory = $true, ParameterSetName = 'ByEntry')]
    [string]$Category,

    [Parameter(Mandatory = $false, ParameterSetName = 'ByEntry')]
    [string]$DatasetPath,

    [Parameter(Mandatory = $true, ParameterSetName = 'ByVersion')]
    [string]$Version,

    [Parameter(Mandatory = $false)]
    [string]$Country = "w1"
)

$ErrorActionPreference = 'Stop'

if ($PSCmdlet.ParameterSetName -eq 'ByEntry') {
    if (-not $DatasetPath) { $DatasetPath = Get-BCBenchDatasetPath -Category $Category }
    $Version = Get-BCBenchEntryVersion -InstanceId $InstanceId -Category $Category -DatasetPath $DatasetPath
    Write-Log "Resolved BC version $Version for InstanceId $InstanceId" -Level Info
}

Import-Module BcContainerHelper -Force -DisableNameChecking

[string] $artifactUrl = Get-BCArtifactUrl -version $Version -country $Country -select 'Latest'
if (-not $artifactUrl) { throw "No BC artifact URL resolved for version $Version ($Country)" }
Write-Log "Downloading artifact: $artifactUrl" -Level Info

$paths = Download-Artifacts -artifactUrl $artifactUrl -includePlatform

$appCount = (Get-ChildItem -Path $paths -Recurse -File -Filter '*.app' -ErrorAction SilentlyContinue | Measure-Object).Count
if ($appCount -eq 0) { throw "No *.app symbol files found under: $($paths -join ', ')" }

Write-Log "Artifact ready: $appCount *.app files cached under $($paths -join ', ')" -Level Success
