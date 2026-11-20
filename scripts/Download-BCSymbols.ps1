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
.PARAMETER Tier
    Dataset tier: gold (default) or challenge.
.PARAMETER Country
    BC artifact country (default: w1).
.PARAMETER Version
    Explicit BC version for runs without a dataset entry.
.EXAMPLE
    .\scripts\Download-BCSymbols.ps1 -Category bug-fix -InstanceId bug-fix__job-budget-report-1
#>
[CmdletBinding(DefaultParameterSetName = 'Dataset')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Dataset')]
    [string]$InstanceId,

    [Parameter(Mandatory = $true, ParameterSetName = 'Dataset')]
    [string]$Category,

    [Parameter(Mandatory = $false)]
    [string]$Tier = "gold",

    [Parameter(Mandatory = $false)]
    [string]$DatasetPath,

    [Parameter(Mandatory = $true, ParameterSetName = 'Version')]
    [ValidatePattern('^\d+\.\d+(\.\d+\.\d+)?$')]
    [string]$Version,

    [Parameter(Mandatory = $false)]
    [string]$Country = "w1"
)

$ErrorActionPreference = 'Stop'

if ($PSCmdlet.ParameterSetName -eq 'Dataset') {
    if (-not $DatasetPath) { $DatasetPath = Get-BCBenchDatasetPath -Category $Category -Tier $Tier }
    $Version = Get-BCBenchEntryVersion -InstanceId $InstanceId -Category $Category -DatasetPath $DatasetPath
}
Write-Log "Resolved BC version $Version" -Level Info

Import-Module BcContainerHelper -Force -DisableNameChecking

[string] $artifactUrl = Get-BCArtifactUrl -version $version -country $Country -select 'Latest'
if (-not $artifactUrl) { throw "No BC artifact URL resolved for version $version ($Country)" }
Write-Log "Downloading artifact: $artifactUrl" -Level Info

$paths = Download-Artifacts -artifactUrl $artifactUrl -includePlatform

$appCount = (Get-ChildItem -Path $paths -Recurse -File -Filter '*.app' -ErrorAction SilentlyContinue | Measure-Object).Count
if ($appCount -eq 0) { throw "No *.app symbol files found under: $($paths -join ', ')" }

Write-Log "Artifact ready: $appCount *.app files cached under $($paths -join ', ')" -Level Success
