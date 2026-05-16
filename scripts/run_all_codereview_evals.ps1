# Runs all code-review evaluations in dataset/codereview.jsonl.
#
# Keeps each entry result in its own run folder to avoid overwriting previous results.
#
# Usage:
#   pwsh scripts/run_all_codereview_evals.ps1
#   pwsh scripts/run_all_codereview_evals.ps1 -RepoPath "C:\repos\evals\BCApps\"

param(
    [string]$Dataset = "dataset/codereview.jsonl",
    [string]$RepoPath = "C:\repos\evals\BCApps\",
    [string]$OutputDir = "evaluation_results",
    [string]$RunPrefix = "copilot_codereview"
)

if (-not (Test-Path $Dataset)) {
    throw "Dataset file not found: $Dataset"
}

$batchId = Get-Date -Format "yyyyMMdd-HHmmss"
$batchOutputDir = Join-Path $OutputDir "$RunPrefix-$batchId"
New-Item -ItemType Directory -Path $batchOutputDir -Force | Out-Null

$ids = Get-Content $Dataset | ForEach-Object {
    try {
        ($_.Trim() | ConvertFrom-Json).instance_id
    }
    catch {
        # skip invalid lines
    }
} | Where-Object { $_ }

Write-Host "Found $($ids.Count) code-review entries."
Write-Host "Batch output root: $batchOutputDir"

$succeeded = 0
$failed = @()

foreach ($id in $ids) {
    $entryRunId = $id

    Write-Host "`n=== Running evaluation for: $id ==="
    uv run bcbench -v evaluate copilot $id --category code-review --repo-path $RepoPath --output-dir $batchOutputDir --run-id $entryRunId

    if ($LASTEXITCODE -ne 0) {
        $failed += [PSCustomObject]@{
            InstanceId = $id
            ExitCode = $LASTEXITCODE
        }

        Write-Host "[ERROR] Evaluation failed for $id (exit code $LASTEXITCODE)" -ForegroundColor Red
    }
    else {
        $succeeded += 1
    }
}

Write-Host "`nAll code-review evaluations complete."
Write-Host "Succeeded: $succeeded"
Write-Host "Failed: $($failed.Count)"
Write-Host "Results root: $batchOutputDir"

if ($failed.Count -gt 0) {
    Write-Host "`nFailed entries:" -ForegroundColor Yellow
    $failed | Format-Table -AutoSize
}
