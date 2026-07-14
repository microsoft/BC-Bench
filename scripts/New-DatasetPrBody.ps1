<#
.SYNOPSIS
Build the markdown body for the dataset-refresh draft PR.

.DESCRIPTION
Joins collected entries (from Collect-And-Screen.ps1 -CollectedFile) to their
dataset-validation matrix-job URLs, producing a markdown bullet per entry. An
entry whose job URL cannot be resolved falls back to the run-level URL.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$CollectedFile,
    [string]$JobsFile,
    [string]$RunUrl,
    [Parameter(Mandatory)][string]$Repo,
    [Parameter(Mandatory)][string]$Week
)

$ErrorActionPreference = 'Stop'

$entries = @(Get-Content -Raw -Path $CollectedFile | ConvertFrom-Json)

$jobMap = @{}
if ($JobsFile -and (Test-Path $JobsFile)) {
    foreach ($job in @(Get-Content -Raw -Path $JobsFile | ConvertFrom-Json)) {
        if ($job.name) { $jobMap[[string]$job.name] = [string]$job.html_url }
    }
}

$lines = @(
    "Automated dataset refresh: bug-fix candidates collected from ``$Repo`` for ISO week $Week.",
    '',
    'Each entry links to the `dataset-validation` job that builds it and checks the FAIL_TO_PASS transition (test fails on base, passes after the gold patch). **Merge only once every linked job is green.**',
    ''
)

foreach ($entry in $entries) {
    $url = if ($jobMap.ContainsKey([string]$entry.Id)) { $jobMap[[string]$entry.Id] } elseif ($RunUrl) { $RunUrl } else { $null }
    $validation = if ($url) { " — 🔬 [validation]($url)" } else { '' }
    $lines += "- ``$($entry.Id)`` ([PR #$($entry.Pr)]($($entry.Url)))$validation"
}

$lines += ''
$lines += '> Draft PR — requires human review. Screening is a static filter only; correctness is proven by the linked validation jobs.'

$lines -join "`n"
