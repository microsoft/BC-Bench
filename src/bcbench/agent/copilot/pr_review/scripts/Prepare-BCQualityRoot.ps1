<#
.SYNOPSIS
    Clone/copy + filter BCQuality into a root the BC-ALAgents engine can consume.

.DESCRIPTION
    Mirrors the `resolve` -> "Fetch and filter BCQuality" step of the engine's
    reusable review.yml so BC-Bench prepares BCQUALITY_ROOT exactly the way PROD
    does: read the engine's pinned repo/ref via Get-BCQualityConfig.ps1, shallow
    fetch that ref, then run Invoke-BCQualityFilter.ps1 over the checkout.

    Honors the same BCQUALITY_* environment overrides Get-BCQualityConfig reads
    (e.g. BCQUALITY_REPO, BCQUALITY_REF), so a caller can pin a different content
    repo/ref (such as a private branch or fork) without editing the engine.

    Pass -LocalPath to iterate on a local BCQuality checkout without pushing: the
    checkout is COPIED into -Root (excluding .git) and filtered there, so the
    original working tree is never modified (the filter deletes files). This is the
    fast inner loop for optimizing BCQuality structure and re-scoring in BC-Bench.

    Emits the resolved root and SHA as `root=<path>` / `sha=<sha>` lines on
    stdout for the Python caller to parse.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $EngineRoot,
    [Parameter(Mandatory)] [string] $Root,
    [string] $LocalPath
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

# Get-BCQualityConfig honors BCQUALITY_REPO/REF and the knowledge/layer overrides;
# the resulting $cfg drives both the fetch (repo/ref) and the filter (allow/deny).
$cfg = & $getConfig

if ($LocalPath) {
    $src = (Resolve-Path -LiteralPath $LocalPath).Path
    if (-not (Test-Path -LiteralPath $src)) { throw "BCQuality -LocalPath does not exist: $src" }

    Write-Host "Copying local BCQuality from $src into $Root (excluding .git)"
    if (Test-Path -LiteralPath $Root) { Remove-Item -LiteralPath $Root -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    Get-ChildItem -LiteralPath $src -Force | Where-Object { $_.Name -ne '.git' } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Root -Recurse -Force
    }

    # Provenance: use the source checkout's HEAD sha when it is a git repo.
    $resolvedSha = 'local'
    $headSha = (& git -C $src rev-parse HEAD 2>$null)
    if ($LASTEXITCODE -eq 0 -and $headSha) { $resolvedSha = "local:$($headSha.Trim())" }
    Write-Host "BCQuality local source SHA: $resolvedSha"
}
else {
    $repo = $cfg.bcquality.repo
    $ref = $cfg.bcquality.ref

    Write-Host "Fetching BCQuality from $repo@$ref into $Root"
    if (Test-Path -LiteralPath $Root) { Remove-Item -LiteralPath $Root -Recurse -Force }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Root) | Out-Null
    if ($repo -match '^[^/\\]+/[^/\\]+$') {
        gh repo clone $repo $Root -- --depth=1 "--revision=$ref" --quiet
        if ($LASTEXITCODE -ne 0) { throw "gh clone of BCQuality ref '$repo@$ref' failed (exit $LASTEXITCODE)" }
    }
    else {
        New-Item -ItemType Directory -Force -Path $Root | Out-Null
        git -C $Root init -q
        git -C $Root remote add origin $repo
        git -C $Root fetch --depth=1 origin "$ref"
        if ($LASTEXITCODE -ne 0) { throw "git fetch of BCQuality ref '$ref' failed (exit $LASTEXITCODE)" }
        git -C $Root checkout -q FETCH_HEAD
        if ($LASTEXITCODE -ne 0) { throw "git checkout of BCQuality ref '$ref' failed (exit $LASTEXITCODE)" }
    }

    $resolvedSha = (& git -C $Root rev-parse HEAD).Trim()
    Write-Host "BCQuality resolved SHA: $resolvedSha"
}

& $filter -BCQualityRoot $Root -Config $cfg | Out-Null

"root=$Root"
"sha=$resolvedSha"
