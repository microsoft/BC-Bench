<#
.SYNOPSIS
    Clone/copy + filter BCQuality into a root the BC-ALAgents engine can consume.

.DESCRIPTION
    Mirrors the `resolve` -> "Fetch and filter BCQuality" step of the engine's
    reusable review.yml so BC-Bench prepares BCQUALITY_ROOT exactly the way PROD
    does: read the engine's pinned repo/ref via Get-BCQualityConfig.ps1, shallow
    fetch that ref, then run Invoke-BCQualityFilter.ps1 over the checkout.

    CandidateRepo/CandidateRef redirect only the fetch, so an unmerged BCQuality
    revision can be evaluated without editing the engine pin. The filter still
    runs from the engine's own configuration, so a candidate is evaluated under
    baseline rules rather than rules it supplied itself.

    Emits `root=<path>` plus the baseline and executed coordinates on stdout, so
    the caller can record what actually ran instead of assuming the pin.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $EngineRoot,
    [Parameter(Mandatory)] [string] $Root,
    [string] $CandidateRepo,
    [string] $CandidateRef
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scripts = Join-Path $EngineRoot 'agents' 'ALReviewAgent' 'scripts'
$getConfig = Join-Path $scripts 'Get-BCQualityConfig.ps1'
$filter = Join-Path $scripts 'Invoke-BCQualityFilter.ps1'

if (-not (Test-Path $getConfig)) { throw "Get-BCQualityConfig.ps1 not found under '$scripts' - check engine path." }

if (-not (Get-Module -ListAvailable -Name powershell-yaml)) {
    Install-Module powershell-yaml -Scope CurrentUser -Force -AllowClobber
}

# The engine configuration drives both the BCQuality fetch and filter.
$cfg = & $getConfig
$baselineRepo = $cfg.bcquality.repo
$baselineRef = $cfg.bcquality.ref

$repo = if ($CandidateRepo) { $CandidateRepo } else { $baselineRepo }
$ref = if ($CandidateRef) { $CandidateRef } else { $baselineRef }

Write-Host "Fetching BCQuality from $repo@$ref into $Root"
if ($repo -ne $baselineRepo -or $ref -ne $baselineRef) {
    Write-Host "Candidate override in effect; baseline is $baselineRepo@$baselineRef"
}
if (Test-Path -LiteralPath $Root) { Remove-Item -LiteralPath $Root -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Root | Out-Null
git -C $Root init -q
git -C $Root remote add origin $repo
git -C $Root fetch --depth=1 origin "$ref"
if ($LASTEXITCODE -ne 0) { throw "git fetch of BCQuality ref '$ref' failed (exit $LASTEXITCODE)" }
git -C $Root checkout -q FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "git checkout of BCQuality ref '$ref' failed (exit $LASTEXITCODE)" }

# A ref is mutable, so report the commit the fetch actually landed on.
$resolvedCommit = "$(git -C $Root rev-parse HEAD)".Trim()

& $filter -BCQualityRoot $Root -Config $cfg | Out-Null

"root=$Root"
"baseline-repo=$baselineRepo"
"baseline-ref=$baselineRef"
"resolved-repo=$repo"
"resolved-ref=$ref"
"resolved-commit=$resolvedCommit"
