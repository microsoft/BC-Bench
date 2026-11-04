param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("baseline", "candidate")]
    [string] $Variant,

    [Parameter(Mandatory = $true)]
    [ValidateSet("authority", "ordinary-quality")]
    [string] $Lane,

    [Parameter(Mandatory = $true)]
    [string] $OutputDir,

    [Parameter(Mandatory = $true)]
    [string] $ToolPath,

    [switch] $DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$ConfigPath = Join-Path $repoRoot "dataset\experiments\bcal_authority_provenance_v1.json"
$config = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
$githubHost = $config.github.host
$githubRepository = $config.github.repository
& gh auth status --hostname $githubHost --active 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BC-Bench repository operations require an active authenticated $githubHost account."
}
$previousGitHubHost = $env:GH_HOST
try {
    $env:GH_HOST = $githubHost
    $accessibleRepository = (& gh repo view $githubRepository --json nameWithOwner --jq .nameWithOwner 2>$null | Out-String).Trim()
}
finally {
    $env:GH_HOST = $previousGitHubHost
}
if ($LASTEXITCODE -ne 0 -or $accessibleRepository -ne $githubRepository) {
    throw "The active $githubHost account cannot access $githubRepository. GHE accounts are not accepted."
}
$excludedEntries = @($config.excluded_entries.instance_id)
$package = $config.packages.$Variant
if (-not $package.published) {
    throw "The $Variant BCal workspace-seeding package is not published in the experiment manifest."
}
$requiredPackageFields = @(
    "package_version",
    "installed_identity",
    "package_source_commit_sha",
    "workspace_seed_patch_id",
    "nupkg_file",
    "nupkg_sha256",
    "feed",
    "build_id",
    "build_result"
)
$missingPackageFields = @($requiredPackageFields | Where-Object { -not $package.$_ })
if ($missingPackageFields.Count -ne 0) {
    throw "The $Variant BCal package is missing required immutable inputs: $($missingPackageFields -join ', ')."
}
if ($package.build_result -ne "succeeded") {
    throw "The $Variant BCal package build $($package.build_id) is not final-success: $($package.build_result)."
}
if ($Variant -eq "candidate" -and (-not $package.authority_source_commit_sha -or -not $package.authority_patch_id)) {
    throw "The candidate BCal package must pin the authority source commit and patch ID."
}
$bcal = Join-Path $ToolPath "bcal.exe"
if (-not (Test-Path -LiteralPath $bcal)) {
    throw "BCal executable not found at $bcal."
}
$installedIdentity = (& $bcal --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "BCal version check failed for $bcal."
}
if ($installedIdentity -ne $package.installed_identity) {
    throw "Expected BCal identity '$($package.installed_identity)', found '$installedIdentity'."
}
$packageArchives = @(
    Get-ChildItem -LiteralPath $ToolPath -Recurse -File -Filter *.nupkg |
        Where-Object { $_.Name -ieq $package.nupkg_file }
)
if ($packageArchives.Count -eq 0) {
    throw "Pinned BCal package archive '$($package.nupkg_file)' was not found under $ToolPath."
}
$packageHashes = @($packageArchives | ForEach-Object { (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant() } | Sort-Object -Unique)
if ($packageHashes.Count -ne 1 -or $packageHashes[0] -ne $package.nupkg_sha256) {
    throw "Expected BCal package SHA-256 '$($package.nupkg_sha256)', found '$($packageHashes -join ', ')'."
}

if ($Lane -eq "authority") {
    $category = $config.authority.category
    $entries = @($config.authority.entries)
}
else {
    $category = $config.ordinary_quality.category
    $datasetPath = Join-Path $repoRoot $config.ordinary_quality.dataset_file
    $entries = @(
        Get-Content -Path $datasetPath |
            Where-Object { $_.Trim() } |
            ForEach-Object { ($_ | ConvertFrom-Json).instance_id }
    )
}

$entries = @($entries | Where-Object { $_ -notin $excludedEntries })
if (($entries | Sort-Object -Unique).Count -ne $entries.Count) {
    throw "Experiment selector contains duplicate entries."
}
if (@($entries | Where-Object { $_ -in $excludedEntries }).Count -ne 0) {
    throw "Excluded entries remain in the selected experiment lane."
}
if ($Lane -eq "ordinary-quality" -and $entries.Count -ne $config.ordinary_quality.expected_entry_count) {
    throw "Ordinary-quality selector expected $($config.ordinary_quality.expected_entry_count) entries, found $($entries.Count)."
}

$selection = [ordered]@{
    schema_version = $config.schema_version
    experiment = $config.name
    github = $config.github
    config_sha256 = (Get-FileHash -Algorithm SHA256 -Path $ConfigPath).Hash.ToLowerInvariant()
    variant = $Variant
    package = $package
    execution = $config.execution
    lane = $Lane
    category = $category
    repeat_count = $config.repeat_count
    selected_entries = $entries
    promotion_entries = $entries
    excluded_entries = $config.excluded_entries
}

if ($DryRun) {
    $selection | ConvertTo-Json -Depth 8
    exit 0
}

$missingPrerequisites = @()
if ([string]::IsNullOrWhiteSpace($env:BCAL_LLM_COMMAND)) {
    $missingPrerequisites += "BCAL_LLM_COMMAND for the fixed external-command backend"
}
elseif ($env:BCAL_LLM_COMMAND -notlike "*$($config.execution.bridge.Replace('/', '\'))") {
    $missingPrerequisites += "BCAL_LLM_COMMAND ending in $($config.execution.bridge)"
}
if ($env:BCAL_LLM_MODEL -ne $config.execution.model) {
    $missingPrerequisites += "BCAL_LLM_MODEL=$($config.execution.model)"
}
$symbolRoot = Join-Path $config.execution.symbol_cache "sandbox"
$symbolVersion = Get-ChildItem -Path $symbolRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "$($config.execution.bc_version)*" } |
    Select-Object -First 1
if (-not $symbolVersion -or -not (Get-ChildItem -Path $symbolVersion.FullName -Recurse -Filter *.app -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    $missingPrerequisites += "BC $($config.execution.bc_version) symbols under $symbolRoot"
}
if ($missingPrerequisites) {
    throw "Missing authority experiment prerequisites: $($missingPrerequisites -join '; ')."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$selection | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 -Path (Join-Path $OutputDir "selection.json")

$env:PATH = "$ToolPath;$env:PATH"
foreach ($repeat in 1..$config.repeat_count) {
    $runOutput = Join-Path $OutputDir "$Variant-$Lane-r$repeat"
    $aggregateRun = Join-Path $runOutput "bcal_test_run"
    New-Item -ItemType Directory -Force -Path $aggregateRun | Out-Null
    foreach ($entry in $entries) {
        $workspace = Join-Path $OutputDir "workspaces\$Variant-$Lane-r$repeat\$entry"
        $caseOutput = Join-Path $OutputDir "case-results\$Variant-$Lane-r$repeat\$entry"
        & python -m uv run bcbench evaluate bcal $entry --category $category --repo-path $workspace --output-dir $caseOutput
        if ($LASTEXITCODE -ne 0) {
            throw "BCal evaluation failed for $entry in repetition $repeat."
        }

        $caseRun = Join-Path $caseOutput "bcal_test_run"
        & (Join-Path $PSScriptRoot "Publish-BCalCaseResults.ps1") -CaseRun $caseRun -AggregateRun $aggregateRun -Entry $entry
    }
}
