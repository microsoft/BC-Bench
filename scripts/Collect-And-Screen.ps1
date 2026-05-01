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

.PARAMETER SinceDays
Look at PRs merged within the last N days.

.PARAMETER Limit
Maximum number of merged PRs to consider.

.PARAMETER BaseBranch
Only consider PRs merged into this base branch. Defaults to main.

.PARAMETER SummaryFile
Optional path to append a markdown summary to (e.g. $env:GITHUB_STEP_SUMMARY).

.EXAMPLE
.\scripts\Collect-And-Screen.ps1 -SinceDays 2 -Limit 5
#>

[CmdletBinding()]
param(
    [string]$Repo = 'microsoft/BCApps',
    [int]$SinceDays = 7,
    [int]$Limit = 200,
    [string]$BaseBranch = 'main',
    [string]$SummaryFile
)

$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'BCBenchUtils.psm1') -Force

$latestRelease = Get-LatestReleaseBranch -Repo $Repo
if (-not $latestRelease) { throw "No releases/* branch found in $Repo" }
$envVersion = $latestRelease -replace '^releases/', ''
Write-Log "Latest release branch in $Repo`: $latestRelease (environment_setup_version=$envVersion)" -Level Info

$since = (Get-Date).ToUniversalTime().AddDays(-$SinceDays).ToString('yyyy-MM-dd')
Write-Log "Searching merged PRs in $Repo (base: $BaseBranch) since $since (limit $Limit)" -Level Info

$requiredLabel = 'AL: Apps (W1)'
$jqFilter = "[.[] | select((.labels | length) == 1 and .labels[0].name == `"$requiredLabel`") | .number]"
$prsJson = & gh pr list --repo $Repo --state merged --base $BaseBranch --label $requiredLabel `
    --search "merged:>=$since" --limit $Limit --json 'number,labels' --jq $jqFilter
if ($LASTEXITCODE -ne 0) { throw "gh pr list failed" }

[int[]]$prs = ($prsJson | ConvertFrom-Json)
Write-Log "Found $($prs.Count) merged PR(s) labeled exclusively '$requiredLabel'" -Level Info

$passed = New-Object System.Collections.Generic.List[string]
foreach ($pr in $prs) {
    if ($env:CI -eq 'true') { Write-Host "::group::PR #$pr" }
    Write-Log "Screening PR #$pr" -Level Info

    & uv run bcbench collect screen $pr --repo $Repo
    $screenExit = $LASTEXITCODE

    if ($screenExit -eq 0) {
        & uv run bcbench collect gh $pr --repo $Repo --environment-setup-version $envVersion
        if ($LASTEXITCODE -eq 0) {
            $instanceId = "$($Repo -replace '/', '__')-$pr"
            $passed.Add($instanceId)
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
    $summary += "Repo: ``$Repo``  |  Base: ``$BaseBranch``  |  Env: ``$envVersion``  |  Window: last $SinceDays day(s) (since $since)"
    $summary += ''
    $summary += "Considered: $($prs.Count)"
    $summary += "Passed screening + collected: $($passed.Count)"
    $summary += ''
    foreach ($id in $passed) { $summary += "- ``$id``" }
    Add-Content -Path $SummaryFile -Value ($summary -join [Environment]::NewLine)
}
