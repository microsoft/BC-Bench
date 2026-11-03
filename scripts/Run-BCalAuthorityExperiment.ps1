param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("baseline", "candidate")]
    [string] $Variant,

    [Parameter(Mandatory = $true)]
    [ValidateSet("authority", "ordinary-quality")]
    [string] $Lane,

    [Parameter(Mandatory = $true)]
    [string] $OutputDir,

    [switch] $DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$ConfigPath = Join-Path $repoRoot "dataset\experiments\bcal_authority_provenance_v1.json"
$config = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
$excludedEntries = @($config.excluded_entries.instance_id)

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
    config_sha256 = (Get-FileHash -Algorithm SHA256 -Path $ConfigPath).Hash.ToLowerInvariant()
    variant = $Variant
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

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$selection | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 -Path (Join-Path $OutputDir "selection.json")

foreach ($repeat in 1..$config.repeat_count) {
    $runOutput = Join-Path $OutputDir "$Variant-$Lane-r$repeat"
    foreach ($entry in $entries) {
        & python -m uv run bcbench evaluate bcal $entry --category $category --output-dir $runOutput
        if ($LASTEXITCODE -ne 0) {
            throw "BCal evaluation failed for $entry in repetition $repeat."
        }
    }
}
