<#
.SYNOPSIS
Discover merged PRs in a GitHub repo, screen them with bcbench, and collect passing ones.

.DESCRIPTION
For each merged PR within the lookback window, runs `bcbench collect screen`
and (if it passes) `bcbench collect gh`, writing new dataset entries into
the working tree. Committing/pushing is left to the caller (e.g. the
`collect-and-screen.yml` workflow).

.PARAMETER Repo
Source GitHub repository (OWNER/REPO). Defaults to microsoft/BCApps.

.PARAMETER MergedSince
Only consider PRs merged at or after this UTC timestamp (yyyy-MM-ddTHH:mm:ssZ).
Defaults to the start of the ISO week selected by -WeeksAgo.

.PARAMETER MergedUntil
Only consider PRs merged at or before this UTC timestamp (yyyy-MM-ddTHH:mm:ssZ).
Defaults to the end of the ISO week selected by -WeeksAgo.

.PARAMETER WeeksAgo
Which completed ISO week to collect when -MergedSince/-MergedUntil are omitted.
1 (default) is the last completed week.

.PARAMETER Limit
Maximum number of merged PRs to consider.

.PARAMETER BaseBranch
Only consider PRs merged into this base branch. Defaults to main.

.PARAMETER SummaryFile
Optional path to append a markdown summary to (e.g. $env:GITHUB_STEP_SUMMARY).

.EXAMPLE
.\scripts\Collect-And-Screen.ps1 -WeeksAgo 1 -Limit 5
#>

[CmdletBinding()]
param(
    [string]$Repo = 'microsoft/BCApps',
    [string]$MergedSince,
    [string]$MergedUntil,
    [int]$WeeksAgo = 1,
    [int]$Limit = 200,
    [string]$BaseBranch = 'main',
    [string]$SummaryFile,
    [string]$CollectedFile
)

$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'BCBenchUtils.psm1') -Force

$window = Get-IsoWeekWindow -WeeksAgo $WeeksAgo
$timestampFormat = 'yyyy-MM-ddTHH:mm:ssZ'
if (-not $MergedSince) { $MergedSince = $window.Start.ToString($timestampFormat) }
if (-not $MergedUntil) { $MergedUntil = $window.End.ToString($timestampFormat) }

function ConvertTo-UtcDateTime {
    param([string]$Value)
    [datetime]::Parse($Value, [cultureinfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor [System.Globalization.DateTimeStyles]::AssumeUniversal)
}

$sinceUtc = ConvertTo-UtcDateTime $MergedSince
$untilUtc = ConvertTo-UtcDateTime $MergedUntil
if ($untilUtc -le $sinceUtc) { throw "MergedUntil ($MergedUntil) must be after MergedSince ($MergedSince)" }

$isoWeek = Get-IsoWeekWindow -ReferenceDate $sinceUtc -WeeksAgo 0
$weekLabel = if ($isoWeek.Start -eq $sinceUtc -and $isoWeek.End -eq $untilUtc) { " (ISO week $($isoWeek.Label))" } else { '' }

$latestRelease = Get-LatestReleaseBranch -Repo $Repo
if (-not $latestRelease) { throw "No releases/* branch found in $Repo" }
$envVersion = $latestRelease -replace '^releases/', ''
Write-Log "Latest release branch in $Repo`: $latestRelease (environment_setup_version=$envVersion)" -Level Info

Write-Log "Searching merged PRs in $Repo (base: $BaseBranch) merged $MergedSince..$MergedUntil$weekLabel (limit $Limit)" -Level Info

$requiredLabel = 'AL: Apps (W1)'
$jqFilter = "[.[] | select((.labels | length) == 1 and .labels[0].name == `"$requiredLabel`") | .number]"
$prsJson = & gh pr list --repo $Repo --state merged --base $BaseBranch --label $requiredLabel `
    --search "merged:$MergedSince..$MergedUntil" --limit $Limit --json 'number,labels' --jq $jqFilter
if ($LASTEXITCODE -ne 0) { throw "gh pr list failed" }

[int[]]$prs = ($prsJson | ConvertFrom-Json)
Write-Log "Found $($prs.Count) merged PR(s) labeled exclusively '$requiredLabel'" -Level Info

$passed = New-Object System.Collections.Generic.List[PSObject]
foreach ($pr in $prs) {
    if ($env:CI -eq 'true') { Write-Host "::group::PR #$pr" }
    Write-Log "Screening PR #$pr" -Level Info

    & uv run bcbench collect screen $pr --repo $Repo
    $screenExit = $LASTEXITCODE

    if ($screenExit -eq 0) {
        & uv run bcbench collect gh $pr --repo $Repo --environment-setup-version $envVersion
        if ($LASTEXITCODE -eq 0) {
            $instanceId = "$($Repo -replace '/', '__')-$pr"
            $passed.Add([PSCustomObject]@{ Id = $instanceId; Pr = $pr; Url = "https://github.com/$Repo/pull/$pr" })
            Write-Log "Collected PR #$pr -> $instanceId" -Level Success
        }
        else {
            Write-Log "PR #$pr passed screening but could not be collected" -Level Warning
        }
    }
    else {
        Write-Log "Skipped PR #$pr (did not pass screening)" -Level Info
    }

    if ($env:CI -eq 'true') { Write-Host "::endgroup::" }
}

if ($SummaryFile) {
    $summary = @()
    $summary += '## Screening summary'
    $summary += ''
    $summary += "Repo: ``$Repo``"
    $summary += ''
    $summary += "Base: ``$BaseBranch``"
    $summary += ''
    $summary += "Env: ``$envVersion``"
    $summary += ''
    $summary += "Window: $MergedSince .. $MergedUntil$weekLabel"
    $summary += ''
    $summary += "Considered: $($prs.Count)"
    $summary += ''
    $summary += "Passed screening + collected: $($passed.Count)"
    $summary += ''
    foreach ($item in $passed) { $summary += "- [$($item.Id)]($($item.Url))" }
    Add-Content -Path $SummaryFile -Value ($summary -join [Environment]::NewLine)
}

if ($CollectedFile -and $passed.Count -gt 0) {
    $passed | ConvertTo-Json -AsArray -Depth 4 | Set-Content -Path $CollectedFile -Encoding utf8
    Write-Log "Wrote $($passed.Count) collected entr$(if ($passed.Count -eq 1) { 'y' } else { 'ies' }) to $CollectedFile" -Level Info
}
