param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "forced-model-activation",
        "host-deterministic",
        "permanent-contract-smoke"
    )]
    [string] $Variant,

    [string] $OutputDir,

    [string] $ToolPath,

    [string] $DuplicateGatePath,

    [switch] $ValidateCohort,

    [switch] $DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $repoRoot "dataset\experiments\bcal_report_skill_gate_b_calibration_v1.json"
$configRelativePath = [IO.Path]::GetRelativePath($repoRoot, $configPath).Replace('\', '/')

& git -C $repoRoot diff --quiet HEAD -- $configRelativePath
if ($LASTEXITCODE -ne 0) {
    throw "Gate B calibration selector must match the checked-in HEAD version: $configRelativePath."
}
$selectorGitBlobSha256 = (& python -c "import hashlib, subprocess, sys; print(hashlib.sha256(subprocess.check_output(['git', '-C', sys.argv[1], 'show', f'HEAD:{sys.argv[2]}'])).hexdigest())" $repoRoot $configRelativePath | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $selectorGitBlobSha256 -notmatch '^[0-9a-f]{64}$') {
    throw "Failed to calculate the checked-in Gate B calibration selector SHA-256."
}

$config = Get-Content -Raw -Path $configPath | ConvertFrom-Json
$variantConfig = $config.variants.$Variant
$entries = @($config.cohort.entries)
$datasetPath = Join-Path $repoRoot "dataset\bcal_scenario.jsonl"
$datasetEntries = @{}
Get-Content -Path $datasetPath | Where-Object { $_.Trim() } | ForEach-Object {
    $entry = $_ | ConvertFrom-Json
    $datasetEntries[$entry.instance_id] = $entry
}

if ($entries.Count -ne 3 -or @($entries | Sort-Object -Unique).Count -ne 3) {
    throw "Gate B calibration must contain exactly three unique probes."
}
if ($config.execution.repeat_count -ne 2) {
    throw "Gate B calibration requires exactly two repetitions."
}
if ($config.cohort.category -ne "bcal-scenario") {
    throw "Gate B calibration may run only the bcal-scenario category."
}
if ($config.scoring.semantic_promotion_metrics_enabled) {
    throw "Gate B calibration must remain excluded from semantic promotion scoring."
}
foreach ($entryId in $entries) {
    if (-not $datasetEntries.ContainsKey($entryId)) {
        throw "Gate B calibration entry is missing from dataset: $entryId."
    }
    $entry = $datasetEntries[$entryId]
    if ($entry.metadata.area -ne "report-gate-b-calibration") {
        throw "Gate B calibration entry is outside the calibration lane: $entryId."
    }
    if (-not $entry.evaluation.compile_required) {
        throw "Gate B calibration entry must require compilation: $entryId."
    }
    if (@($entry.evaluation.deterministic_artifact_assertions).Count -eq 0) {
        throw "Gate B calibration entry must define deterministic artifact assertions: $entryId."
    }
}
if (-not $entries.Contains($variantConfig.entry)) {
    throw "Gate B calibration variant entry is not in the immutable cohort."
}

$selection = [ordered]@{
    schema_version = $config.schema_version
    experiment = $config.name
    purpose = $config.purpose
    github = $config.github
    selector_git_blob_sha256 = $selectorGitBlobSha256
    authorization = $config.authorization
    variant = $Variant
    variant_configuration = $variantConfig
    execution = $config.execution
    package = $variantConfig.package
    skill = $config.skill
    category = $config.cohort.category
    repeat_count = $config.execution.repeat_count
    selected_entries = @($variantConfig.entry)
    calibration_entries = @($variantConfig.entry)
    invariants = $config.invariants
    scoring = $config.scoring
}
$selectionJson = (($selection | ConvertTo-Json -Depth 10) -replace "`r`n", "`n") + "`n"

if ($ValidateCohort) {
    [Console]::Out.Write($selectionJson)
    exit 0
}

if ($config.authorization.state -ne "authorized" -or -not $config.authorization.authorized_study_id) {
    throw "Gate B calibration dispatch is blocked until coordinator authorization is recorded."
}
if (-not $config.execution.model) {
    throw "Authorized Gate B calibration is missing the exact model."
}
if (-not $variantConfig.configuration_id -or $null -eq $variantConfig.package) {
    throw "Authorized Gate B calibration variant is missing its immutable configuration and package identity."
}
& git -C $repoRoot merge-base --is-ancestor $config.github.required_fixed_base_sha HEAD
if ($LASTEXITCODE -ne 0) {
    throw "Current HEAD is not based on repaired microsoft/BC-Bench#1011 head $($config.github.required_fixed_base_sha)."
}

$package = $variantConfig.package
$requiredPackageFields = @(
    "package_id",
    "package_version",
    "installed_identity",
    "package_source_commit_sha",
    "variant_patch_sha",
    "nupkg_file",
    "nupkg_sha256",
    "nupkg_size",
    "feed",
    "build_id",
    "build_result",
    "published"
)
$missingPackageFields = @($requiredPackageFields | Where-Object { $null -eq $package.$_ -or $package.$_ -eq "" })
if ($missingPackageFields.Count -ne 0 -or -not $package.published -or $package.build_result -ne "succeeded") {
    throw "Authorized Gate B calibration package identity is incomplete or unpublished."
}
if (-not $DuplicateGatePath -or -not (Test-Path -LiteralPath $DuplicateGatePath)) {
    throw "Gate B calibration dispatch requires a duplicate-gate receipt."
}
$duplicateGate = Get-Content -Raw -LiteralPath $DuplicateGatePath | ConvertFrom-Json
if ($duplicateGate.github_matches -ne 0 -or $duplicateGate.kusto_matches -ne 0) {
    throw "Duplicate gate failed: GitHub=$($duplicateGate.github_matches), Kusto=$($duplicateGate.kusto_matches)."
}
if ($duplicateGate.study_id -ne $config.authorization.authorized_study_id -or $duplicateGate.selector_git_blob_sha256 -ne $selectorGitBlobSha256) {
    throw "Duplicate-gate receipt does not match the authorized calibration study and selector provenance."
}
if (-not $ToolPath) {
    throw "ToolPath is required for authorized calibration dry-runs and execution."
}
$bcal = Join-Path $ToolPath "bcal.exe"
if (-not (Test-Path -LiteralPath $bcal)) {
    throw "BCal executable not found at $bcal."
}
$installedIdentity = (& $bcal --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $installedIdentity -ne $package.installed_identity) {
    throw "Expected BCal identity '$($package.installed_identity)', found '$installedIdentity'."
}
$packageArchive = Get-ChildItem -LiteralPath $ToolPath -Recurse -File -Filter $package.nupkg_file | Select-Object -First 1
if (-not $packageArchive) {
    throw "Pinned BCal package archive '$($package.nupkg_file)' was not found under ToolPath."
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $packageArchive.FullName).Hash.ToLowerInvariant() -ne $package.nupkg_sha256 -or $packageArchive.Length -ne $package.nupkg_size) {
    throw "Pinned BCal package bytes do not match the authorized SHA-256 and size."
}
if (
    [string]::IsNullOrWhiteSpace($env:BCAL_LLM_COMMAND) -or
    $env:BCAL_LLM_COMMAND -notlike "*$($config.execution.bridge.Replace('/', '\'))" -or
    $env:BCAL_LLM_MODEL -ne $config.execution.model
) {
    throw "Gate B calibration requires the authorized external-command bridge and exact model."
}
$symbolRoot = Join-Path $config.execution.symbol_cache "sandbox"
$symbolVersion = Get-ChildItem -Path $symbolRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "$($config.execution.bc_version)*" } |
    Select-Object -First 1
if (-not $symbolVersion -or -not (Get-ChildItem -Path $symbolVersion.FullName -Recurse -Filter *.app -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    throw "Gate B calibration requires BC $($config.execution.bc_version) symbols under $symbolRoot."
}

if ($DryRun) {
    [Console]::Out.Write($selectionJson)
    exit 0
}
if (-not $OutputDir) {
    throw "OutputDir is required for execution."
}
if ((Test-Path -LiteralPath $OutputDir) -and (Get-ChildItem -LiteralPath $OutputDir -Force | Select-Object -First 1)) {
    throw "Gate B calibration output collision: OutputDir is not empty."
}

$env:PATH = "$ToolPath;$env:PATH"
$env:BCBENCH_BCAL_SKILL_ACTIVATION_POLICY = $variantConfig.skill_activation_policy
$env:BCBENCH_BCAL_SKILL_ACTIVATION_SOURCE = $variantConfig.skill_activation_source
$env:BCBENCH_BCAL_EXPECTED_ACTIVATION_MODE = $variantConfig.expected_activation_mode
$env:BCBENCH_BCAL_REQUESTED_TOOL_CALL_ID = $variantConfig.requested_tool_call_id
$env:BCBENCH_BCAL_REQUIRE_OFFERED_TOOL_EVIDENCE = $variantConfig.require_offered_tool_evidence.ToString().ToLowerInvariant()
$env:BCBENCH_BCAL_REPORT_SKILL_ID = $config.skill.id
$env:BCBENCH_BCAL_SKILL_CONTRACT_VERSION = $config.skill.contract_version
$env:BCBENCH_BCAL_SKILL_CONTENT_SHA256 = $config.skill.content_sha256
$env:BCBENCH_BCAL_SKILL_REVISION = $config.skill.revision
$env:BCBENCH_BCAL_SKILL_CATALOG_SEGMENT = $config.skill.catalog_segment
$env:BCBENCH_BCAL_SKILL_ACTIVATED_SEGMENT = $config.skill.activated_segment

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
[IO.File]::WriteAllText((Join-Path $OutputDir "selection.json"), $selectionJson, [Text.UTF8Encoding]::new($false))
[IO.File]::Copy($DuplicateGatePath, (Join-Path $OutputDir "duplicate-gate.json"), $false)
foreach ($repeat in 1..$config.execution.repeat_count) {
    $caseOutput = Join-Path $OutputDir "$Variant-r$repeat"
    $workspace = Join-Path $caseOutput "workspace"
    & python -m uv run bcbench evaluate bcal $variantConfig.entry --category $config.cohort.category --repo-path $workspace --output-dir $caseOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Gate B calibration failed for $Variant repetition $repeat."
    }
}
