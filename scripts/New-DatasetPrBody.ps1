<#
.SYNOPSIS
Build the markdown body for the dataset-refresh draft PR.

.DESCRIPTION
Splits collected entries into those that passed dataset-validation (job
conclusion 'success') and those that did not, rendering an Included section
(in the PR diff) and, when any failed, an Excluded section (documented only).
An entry with no resolvable job is treated as not-passed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$CollectedFile,
    [string]$JobsFile,
    [string]$RunUrl,
    [Parameter(Mandatory)][string]$Repo,
    [Parameter(Mandatory)][string]$Week,
    [string]$MergedSince,
    [string]$MergedUntil
)

$ErrorActionPreference = 'Stop'

$entries = @()
if (Test-Path $CollectedFile) {
    $entries = @(Get-Content -Raw -Path $CollectedFile | ConvertFrom-Json)
}

$jobMap = @{}
if ($JobsFile -and (Test-Path $JobsFile)) {
    foreach ($job in @(Get-Content -Raw -Path $JobsFile | ConvertFrom-Json)) {
        if ($job.name) { $jobMap[[string]$job.name] = $job }
    }
}

function Format-EntryLine {
    param($Entry, [switch]$WithConclusion)
    $job = $jobMap[[string]$Entry.Id]
    $url = if ($job -and $job.html_url) { [string]$job.html_url } elseif ($RunUrl) { $RunUrl } else { $null }
    $validation = if ($url) { " — 🔬 [validation]($url)" } else { '' }
    $line = "- ``$($Entry.Id)`` ([PR #$($Entry.Pr)]($($Entry.Url)))$validation"
    if ($WithConclusion) {
        $conclusion = if ($job -and $job.conclusion) { [string]$job.conclusion } else { 'incomplete' }
        $line += " — **$conclusion**"
    }
    $line
}

$passed = @($entries | Where-Object { $j = $jobMap[[string]$_.Id]; $j -and $j.conclusion -eq 'success' })
$failed = @($entries | Where-Object { $j = $jobMap[[string]$_.Id]; -not ($j -and $j.conclusion -eq 'success') })

$mergeWindow = if ($MergedSince -and $MergedUntil) { " (merged $MergedSince .. $MergedUntil)" } else { '' }

$lines = @(
    "Automated dataset refresh: bug-fix candidates collected from ``$Repo`` for ISO week $Week$mergeWindow.",
    '',
    '## ✅ Included (passed validation)',
    '',
    'These entries passed `dataset-validation` (build + FAIL_TO_PASS transition) and are included in this PR.',
    ''
)

if ($passed.Count -gt 0) {
    foreach ($entry in $passed) { $lines += (Format-EntryLine -Entry $entry) }
}
else {
    $lines += '_None._'
}

if ($failed.Count -gt 0) {
    $lines += ''
    $lines += '## ❌ Excluded (failed / incomplete validation — documented, not included)'
    $lines += ''
    $lines += 'These entries did not pass validation and are **not** part of this PR''s changes; listed for the record.'
    $lines += ''
    foreach ($entry in $failed) { $lines += (Format-EntryLine -Entry $entry -WithConclusion) }
}

$lines += ''
$lines += '> Draft PR — requires human review. Screening is a static filter only; correctness is proven by the linked validation jobs.'

$lines -join "`n"
