using module .\DatasetEntry.psm1
using module .\BCBenchUtils.psm1

<#
    .Synopsis
    Merges all evaluation result JSONL files into a single JSONL file.
    .Description
    Designed to be run after `gh run download <run-id> --dir .\evaluation_results\ -p "evaluation-results-*"`
#>

param(
    [string] $InputDir = "$PSScriptRoot\..\evaluation_results",
    [string] $DatasetFile = (Get-BCBenchDatasetPath)
)

$resultFolders = Get-ChildItem -Path $InputDir -Directory -Filter "evaluation-results-*"
if ($resultFolders.Count -eq 0) {
    Write-Log "No evaluation-results-* folders found in $InputDir" -Level Error
    exit 1
}

[string] $runId = ($resultFolders[0].Name -split '-')[2]
$OutputFile = Join-Path $InputDir "$runId.jsonl"

Write-Log "Merging results for run $runId to $OutputFile"

# Merge all JSONL files
$jsonlFiles = $resultFolders | ForEach-Object { Get-ChildItem $_.FullName -Filter "*.jsonl" -Recurse }
$evaluatedIds = $jsonlFiles | Get-Content | Tee-Object -FilePath $OutputFile | ForEach-Object { ($_ | ConvertFrom-Json).instance_id }

Write-Log "Merged $($evaluatedIds.Count) results from $($jsonlFiles.Count) files" -Level Success

# Report missing instances
$datasetIds = (Get-DatasetEntries -DatasetPath $DatasetFile).instance_id
$missing = $datasetIds | Where-Object { $_ -notin $evaluatedIds }

if ($missing) {
    Write-Log "Missing $($missing.Count) of $($datasetIds.Count) instances:" -Level Warning
    $missing | ForEach-Object { Write-Log "  $_" -Level Warning }
}
else {
    Write-Log "All $($datasetIds.Count) instances evaluated!" -Level Success
}

# Cleanup
$resultFolders | Remove-Item -Recurse -Force
Write-Log "Cleaned up $($resultFolders.Count) folders" -Level Success

Write-Host "`nDone! Deleted $($resultFolders.Count) folders."
