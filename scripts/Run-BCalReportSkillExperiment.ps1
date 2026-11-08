param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "permanent-full-report-guidance",
        "model-triggered-report-skill",
        "host-triggered-report-skill"
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
$configPath = Join-Path $repoRoot "dataset\experiments\bcal_report_skill_progressive_disclosure_v1.json"
$configRelativePath = [IO.Path]::GetRelativePath($repoRoot, $configPath).Replace('\', '/')

& git -C $repoRoot diff --quiet HEAD -- $configRelativePath
if ($LASTEXITCODE -ne 0) {
    throw "Report experiment selector must match the checked-in HEAD version: $configRelativePath."
}
$selectorGitBlobSha256 = (& python -c "import hashlib, subprocess, sys; print(hashlib.sha256(subprocess.check_output(['git', '-C', sys.argv[1], 'show', f'HEAD:{sys.argv[2]}'])).hexdigest())" $repoRoot $configRelativePath | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $selectorGitBlobSha256 -notmatch '^[0-9a-f]{64}$') {
    throw "Failed to calculate the checked-in report experiment selector SHA-256."
}

$config = Get-Content -Raw -Path $configPath | ConvertFrom-Json
$entries = @($config.cohort.entries)
$uniqueEntries = @($entries | Sort-Object -Unique)
if ($entries.Count -ne 6 -or $uniqueEntries.Count -ne $entries.Count) {
    throw "Report experiment cohort must contain exactly six unique entries."
}
if ($config.execution.repeat_count -lt 2) {
    throw "Report experiment requires at least two repetitions."
}
if ($config.cohort.category -ne "bcal-scenario") {
    throw "Report experiment may run only the bcal-scenario category."
}
if (@($entries | Where-Object { $_ -like "*control-tower*" }).Count -ne 0) {
    throw "Control Tower is prohibited from the report experiment."
}

$datasetPath = Join-Path $repoRoot "dataset\bcal_scenario.jsonl"
$datasetEntries = @{}
Get-Content -Path $datasetPath | Where-Object { $_.Trim() } | ForEach-Object {
    $entry = $_ | ConvertFrom-Json
    $datasetEntries[$entry.instance_id] = $entry
}
foreach ($entryId in $entries) {
    if (-not $datasetEntries.ContainsKey($entryId)) {
        throw "Report experiment entry is missing from dataset: $entryId."
    }
    if ($datasetEntries[$entryId].metadata.area -ne "report-progressive-disclosure") {
        throw "Report experiment entry is outside the focused report lane: $entryId."
    }
    if (-not $datasetEntries[$entryId].evaluation.compile_required) {
        throw "Report experiment entry must require compilation: $entryId."
    }
    if (@($datasetEntries[$entryId].evaluation.artifact_assertions).Count -eq 0 -or @($datasetEntries[$entryId].evaluation.deterministic_artifact_assertions).Count -eq 0) {
        throw "Report experiment entry must define semantic and deterministic artifact assertions: $entryId."
    }
}

$variantConfig = $config.variants.$Variant
$selection = [ordered]@{
    schema_version = $config.schema_version
    experiment = $config.name
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
    selected_entries = $entries
    promotion_entries = $entries
    excluded_entries = $config.excluded_entries
    invariants = $config.invariants
    promotion = $config.promotion
}
$selectionJson = (($selection | ConvertTo-Json -Depth 10) -replace "`r`n", "`n") + "`n"

if ($ValidateCohort) {
    [Console]::Out.Write($selectionJson)
    exit 0
}

if ($config.authorization.state -ne "authorized" -or -not $config.authorization.authorized_study_id) {
    throw "Report experiment dispatch is blocked until the coordinator supplies and authorizes the exact study configuration."
}
if (-not $config.github.required_fixed_base_sha) {
    throw "Authorized report experiment is missing the exact fixed microsoft/BC-Bench#1011 head."
}
& git -C $repoRoot merge-base --is-ancestor $config.github.required_fixed_base_sha HEAD
if ($LASTEXITCODE -ne 0) {
    throw "Current HEAD is not based on the authorized fixed microsoft/BC-Bench#1011 head $($config.github.required_fixed_base_sha)."
}
$requiredExecutionFields = @("model")
$missingExecutionFields = @($requiredExecutionFields | Where-Object { -not $config.execution.$_ })
if ($missingExecutionFields.Count -ne 0) {
    throw "Authorized report experiment is missing exact execution fields: $($missingExecutionFields -join ', ')."
}
$requiredPackageFields = @(
    "package_id",
    "package_version",
    "installed_identity",
    "package_source_commit_sha",
    "nupkg_file",
    "nupkg_sha256",
    "nupkg_size",
    "feed",
    "build_id",
    "build_result",
    "published"
)
$package = $variantConfig.package
$missingPackageFields = @($requiredPackageFields | Where-Object { $null -eq $package.$_ -or $package.$_ -eq "" })
if ($missingPackageFields.Count -ne 0) {
    throw "Authorized report experiment package is missing immutable fields: $($missingPackageFields -join ', ')."
}
if (-not $package.published -or $package.build_result -ne "succeeded") {
    throw "Authorized report experiment package must be published from a final-success build."
}
$requiredVariantFields = @("configuration_id", "expected_activation_mode", "requested_tool_call_id")
if ($variantConfig.skill_activation_policy -eq "required") {
    $requiredVariantFields += @("skill_activation_source")
}
$missingVariantFields = @($requiredVariantFields | Where-Object { -not $variantConfig.$_ })
if ($missingVariantFields.Count -ne 0) {
    throw "Authorized report experiment variant is missing exact configuration fields: $($missingVariantFields -join ', ')."
}
if (-not $DuplicateGatePath -or -not (Test-Path -LiteralPath $DuplicateGatePath)) {
    throw "Dispatch requires a duplicate-gate receipt with GitHub and Kusto checks."
}
$duplicateGate = Get-Content -Raw -LiteralPath $DuplicateGatePath | ConvertFrom-Json
if ($duplicateGate.github_matches -ne 0 -or $duplicateGate.kusto_matches -ne 0) {
    throw "Duplicate gate failed: GitHub=$($duplicateGate.github_matches), Kusto=$($duplicateGate.kusto_matches)."
}
if ($duplicateGate.study_id -ne $config.authorization.authorized_study_id) {
    throw "Duplicate-gate receipt does not match the authorized study ID."
}
if ($duplicateGate.selector_git_blob_sha256 -ne $selectorGitBlobSha256) {
    throw "Duplicate-gate receipt does not match the checked-in selector provenance."
}

if (-not $ToolPath) {
    throw "ToolPath is required for authorized dry-runs and execution."
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
$packageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $packageArchive.FullName).Hash.ToLowerInvariant()
if ($packageHash -ne $package.nupkg_sha256) {
    throw "Expected BCal package SHA-256 '$($package.nupkg_sha256)', found '$packageHash'."
}
if ($packageArchive.Length -ne $package.nupkg_size) {
    throw "Expected BCal package size '$($package.nupkg_size)', found '$($packageArchive.Length)'."
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
    throw "Missing report experiment prerequisites: $($missingPrerequisites -join '; ')."
}

if ($DryRun) {
    [Console]::Out.Write($selectionJson)
    exit 0
}
if (-not $OutputDir) {
    throw "OutputDir is required for execution."
}
if (Test-Path -LiteralPath $OutputDir) {
    $existingOutput = Get-ChildItem -LiteralPath $OutputDir -Force | Select-Object -First 1
    if ($existingOutput) {
        throw "BCal report experiment output collision: OutputDir is not empty."
    }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$selectionBytes = [Text.UTF8Encoding]::new($false).GetBytes($selectionJson)
[IO.File]::WriteAllBytes((Join-Path $OutputDir "selection.json"), $selectionBytes)
$selectionArtifactSha256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($selectionBytes)).ToLowerInvariant()
[IO.File]::WriteAllText(
    (Join-Path $OutputDir "selection.sha256"),
    "$selectionArtifactSha256  selection.json`n",
    [Text.UTF8Encoding]::new($false)
)
[IO.File]::Copy($DuplicateGatePath, (Join-Path $OutputDir "duplicate-gate.json"), $false)

$env:PATH = "$ToolPath;$env:PATH"
$env:BCBENCH_BCAL_SKILL_ACTIVATION_POLICY = $variantConfig.skill_activation_policy
$env:BCBENCH_BCAL_SKILL_ACTIVATION_SOURCE = $variantConfig.skill_activation_source
$env:BCBENCH_BCAL_EXPECTED_ACTIVATION_MODE = $variantConfig.expected_activation_mode
$env:BCBENCH_BCAL_REQUESTED_TOOL_CALL_ID = $variantConfig.requested_tool_call_id
$env:BCBENCH_BCAL_REPORT_SKILL_ID = $config.skill.id
$env:BCBENCH_BCAL_SKILL_CONTRACT_VERSION = $config.skill.contract_version
$env:BCBENCH_BCAL_SKILL_CONTENT_SHA256 = $config.skill.content_sha256
$env:BCBENCH_BCAL_SKILL_REVISION = $config.skill.revision
$env:BCBENCH_BCAL_SKILL_CATALOG_SEGMENT = $config.skill.catalog_segment
$env:BCBENCH_BCAL_SKILL_ACTIVATED_SEGMENT = $config.skill.activated_segment
foreach ($repeat in 1..$config.execution.repeat_count) {
    $runOutput = Join-Path $OutputDir "$Variant-r$repeat"
    $aggregateRun = Join-Path $runOutput "bcal_test_run"
    New-Item -ItemType Directory -Force -Path $aggregateRun | Out-Null
    foreach ($entry in $entries) {
        $workspace = Join-Path $OutputDir "workspaces\$Variant-r$repeat\$entry"
        $caseOutput = Join-Path $OutputDir "case-results\$Variant-r$repeat\$entry"
        & python -m uv run bcbench evaluate bcal $entry --category $config.cohort.category --repo-path $workspace --output-dir $caseOutput
        if ($LASTEXITCODE -ne 0) {
            throw "BCal report evaluation failed for $entry in repetition $repeat."
        }
        $caseRun = Join-Path $caseOutput "bcal_test_run"
        & (Join-Path $PSScriptRoot "Publish-BCalCaseResults.ps1") -CaseRun $caseRun -AggregateRun $aggregateRun -Entry $entry
    }
}
