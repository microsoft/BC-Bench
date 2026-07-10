[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $EngineScriptsDir,
    [Parameter(Mandatory)][string] $BCQualityRoot,
    [string] $ConfigPath = ''
)

# Replicates the reusable review workflow's "Fetch and filter BCQuality" step
# for offline (BC-Bench) runs: resolve the policy config, shallow-clone the
# BCQuality repo at the pinned ref, prune it to the allowed layers/knowledge,
# and emit the resolved commit SHA on stdout (last line).

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Get-Module -ListAvailable -Name powershell-yaml)) {
    Install-Module powershell-yaml -Scope CurrentUser -Force -AllowClobber | Out-Null
}

$getConfig = Join-Path $EngineScriptsDir 'Get-BCQualityConfig.ps1'
$filter = Join-Path $EngineScriptsDir 'Invoke-BCQualityFilter.ps1'

$cfg = & $getConfig -ConfigPath $ConfigPath
$repo = $cfg.bcquality.repo
$ref = $cfg.bcquality.ref

if (Test-Path $BCQualityRoot) { Remove-Item -Recurse -Force -LiteralPath $BCQualityRoot }
New-Item -ItemType Directory -Force -Path $BCQualityRoot | Out-Null

git -C $BCQualityRoot init -q
git -C $BCQualityRoot remote add origin $repo
git -C $BCQualityRoot fetch --depth=1 origin "$ref"
if ($LASTEXITCODE -ne 0) { throw "git fetch of BCQuality ref '$ref' failed (exit $LASTEXITCODE)" }
git -C $BCQualityRoot checkout -q FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "git checkout of BCQuality ref '$ref' failed (exit $LASTEXITCODE)" }

$resolvedSha = (& git -C $BCQualityRoot rev-parse HEAD).Trim()

& $filter -BCQualityRoot $BCQualityRoot -Config $cfg | Out-Null

Write-Output $resolvedSha
