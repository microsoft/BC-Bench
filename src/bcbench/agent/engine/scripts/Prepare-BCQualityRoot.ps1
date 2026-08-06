<#
.SYNOPSIS
    Clone + filter BCQuality into a root the BC-ALAgents engine can consume.

.DESCRIPTION
    Mirrors the `resolve` -> "Fetch and filter BCQuality" step of the engine's
    reusable review.yml so BC-Bench prepares BCQUALITY_ROOT exactly the way PROD
    does: read the engine's pinned repo/ref via Get-BCQualityConfig.ps1, shallow
    fetch that ref, then run Invoke-BCQualityFilter.ps1 over the checkout.

    Honors the same BCQUALITY_* environment overrides Get-BCQualityConfig reads
    (e.g. BCQUALITY_REF), so a caller can pin a different content ref.

    Emits the resolved root and SHA as `root=<path>` / `sha=<sha>` lines on
    stdout for the Python caller to parse.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $EngineRoot,
    [Parameter(Mandatory)] [string] $Root
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

$cfg = & $getConfig
$repo = $cfg.bcquality.repo
$ref = $cfg.bcquality.ref

Write-Host "Fetching BCQuality from $repo@$ref into $Root"
New-Item -ItemType Directory -Force -Path $Root | Out-Null
git -C $Root init -q
git -C $Root remote add origin $repo
git -C $Root fetch --depth=1 origin "$ref"
if ($LASTEXITCODE -ne 0) { throw "git fetch of BCQuality ref '$ref' failed (exit $LASTEXITCODE)" }
git -C $Root checkout -q FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "git checkout of BCQuality ref '$ref' failed (exit $LASTEXITCODE)" }

$resolvedSha = (& git -C $Root rev-parse HEAD).Trim()
Write-Host "BCQuality resolved SHA: $resolvedSha"

& $filter -BCQualityRoot $Root -Config $cfg | Out-Null

"root=$Root"
"sha=$resolvedSha"
