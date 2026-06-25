using module .\BCBenchUtils.psm1

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
.PARAMETER Country
    BC artifact country (default: w1).
.EXAMPLE
    .\scripts\Download-BCSymbols.ps1 -Category bug-fix -InstanceId bug-fix__job-budget-report-1
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$InstanceId,

    [Parameter(Mandatory = $true)]
    [string]$Category,

    [Parameter(Mandatory = $false)]
    [string]$DatasetPath = (Get-BCBenchDatasetPath -Category $Category),

    [Parameter(Mandatory = $false)]
    [string]$Country = "w1"
)

$ErrorActionPreference = 'Stop'

[string] $version = Get-BCBenchEntryVersion -InstanceId $InstanceId -Category $Category -DatasetPath $DatasetPath
Write-Log "Resolved BC version $version for InstanceId $InstanceId" -Level Info

Import-Module BcContainerHelper -Force -DisableNameChecking

[string] $artifactUrl = Get-BCArtifactUrl -version $version -country $Country -select 'Latest'
if (-not $artifactUrl) { throw "No BC artifact URL resolved for version $version ($Country)" }
Write-Log "Downloading artifact: $artifactUrl" -Level Info

$paths = Download-Artifacts -artifactUrl $artifactUrl -includePlatform

$appCount = (Get-ChildItem -Path $paths -Recurse -File -Filter '*.app' -ErrorAction SilentlyContinue | Measure-Object).Count
if ($appCount -eq 0) { throw "No *.app symbol files found under: $($paths -join ', ')" }

Write-Log "Artifact ready: $appCount *.app files cached under $($paths -join ', ')" -Level Success
