using module .\BCBenchUtils.psm1

<#
    .SYNOPSIS
    Gets evaluation summary from GitHub Actions workflow runs.

    .DESCRIPTION
    Fetches workflow run summaries from the copilot-evaluation.yml workflow and extracts
    failure information including instance IDs, projects, and error messages.

    .PARAMETER RunId
    Optional specific run ID to fetch. If not provided, fetches the most recent run.

    .PARAMETER Last
    Number of recent runs to fetch (default: 1). Ignored if RunId is specified.

    .PARAMETER Branch
    Filter runs by branch name.

    .PARAMETER Status
    Filter runs by status (completed, in_progress, queued, etc.)

    .EXAMPLE
    .\Get-WorkflowSummary.ps1
    # Gets the most recent workflow run summary

    .EXAMPLE
    .\Get-WorkflowSummary.ps1 -Last 5
    # Gets the last 5 workflow run summaries

    .EXAMPLE
    .\Get-WorkflowSummary.ps1 -RunId 12345678
    # Gets summary for a specific run ID
#>

param(
    [Parameter(Mandatory = $false)]
    [string]$RunId,

    [Parameter(Mandatory = $false)]
    [int]$Last = 1,

    [Parameter(Mandatory = $false)]
    [string]$Branch,

    [Parameter(Mandatory = $false)]
    [ValidateSet("completed", "in_progress", "queued", "waiting", "requested", "pending")]
    [string]$Status = "completed",

    [Parameter(Mandatory = $false)]
    [string]$Repository = "microsoft/BC-Bench",

    [Parameter(Mandatory = $false)]
    [string]$Workflow = "copilot-evaluation.yml"
)

function Get-WorkflowRuns {
    param(
        [string]$Repo,
        [string]$WorkflowFile,
        [int]$Limit,
        [string]$BranchFilter,
        [string]$StatusFilter
    )

    $args = @(
        "run", "list",
        "--repo", $Repo,
        "--workflow", $WorkflowFile,
        "--limit", $Limit,
        "--json", "databaseId,displayTitle,conclusion,status,createdAt,headBranch,url"
    )

    if ($BranchFilter) {
        $args += @("--branch", $BranchFilter)
    }

    if ($StatusFilter) {
        $args += @("--status", $StatusFilter)
    }

    $result = gh @args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to fetch workflow runs: $result"
    }

    return $result | ConvertFrom-Json
}

function Get-JobSummary {
    param(
        [string]$Repo,
        [string]$RunId
    )

    # Get jobs for the run
    $jobs = gh run view $RunId --repo $Repo --json jobs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to fetch jobs for run $RunId`: $jobs"
    }

    return ($jobs | ConvertFrom-Json).jobs
}

function Get-RunSummaryMarkdown {
    param(
        [string]$Repo,
        [string]$RunId
    )

    # Use GitHub API to get the run's job summaries
    # The summary is typically in the "summarize" job or similar
    $apiResult = gh api "repos/$Repo/actions/runs/$RunId/jobs" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to fetch run details via API: $apiResult"
    }

    return $apiResult | ConvertFrom-Json
}

function Parse-EvaluationSummary {
    <#
    .SYNOPSIS
    Parses the evaluation summary markdown text to extract failure information.
    #>
    param(
        [string]$SummaryText
    )

    $result = [PSCustomObject]@{
        TotalEntries          = 0
        Model                 = ""
        Category              = ""
        SuccessfulEvaluations = 0
        FailedEvaluations     = 0
        FailedInstances       = @()
        ToolUsage             = @{}
        RawSummary            = $SummaryText
    }

    if ([string]::IsNullOrWhiteSpace($SummaryText)) {
        return $result
    }

    # Parse total entries and model
    if ($SummaryText -match "Total entries processed:\s*(\d+),\s*using\s+(.+)") {
        $result.TotalEntries = [int]$Matches[1]
        $result.Model = $Matches[2].Trim()
    }

    # Parse category
    if ($SummaryText -match "Category:\s*(.+)") {
        $result.Category = $Matches[1].Trim()
    }

    # Parse successful evaluations
    if ($SummaryText -match "Successful evaluations:\s*(\d+)") {
        $result.SuccessfulEvaluations = [int]$Matches[1]
    }

    # Parse failed evaluations
    if ($SummaryText -match "Failed evaluations:\s*(\d+)") {
        $result.FailedEvaluations = [int]$Matches[1]
    }

    # Parse failed instances from the detailed results table
    # Format: Instance ID | Project | Status | Error Message
    $tablePattern = "(?m)^([a-zA-Z_]+__[a-zA-Z0-9-]+)\s*\|\s*(\w+)\s*\|\s*❌\s*Failed\s*\|\s*(.+)$"
    $matches = [regex]::Matches($SummaryText, $tablePattern)

    foreach ($match in $matches) {
        $result.FailedInstances += [PSCustomObject]@{
            InstanceId   = $match.Groups[1].Value.Trim()
            Project      = $match.Groups[2].Value.Trim()
            ErrorMessage = $match.Groups[3].Value.Trim()
        }
    }

    # Alternative table format (tab-separated)
    if ($result.FailedInstances.Count -eq 0) {
        $altPattern = "(?m)^(microsoft[^\s\t]+)\s+(\w+)\s+❌\s*Failed\s+(.+)$"
        $matches = [regex]::Matches($SummaryText, $altPattern)

        foreach ($match in $matches) {
            $result.FailedInstances += [PSCustomObject]@{
                InstanceId   = $match.Groups[1].Value.Trim()
                Project      = $match.Groups[2].Value.Trim()
                ErrorMessage = $match.Groups[3].Value.Trim()
            }
        }
    }

    # Parse tool usage
    $toolPattern = "(?m)^(\w+):\s*([\d.]+)$"
    $toolMatches = [regex]::Matches($SummaryText, $toolPattern)

    foreach ($match in $toolMatches) {
        $toolName = $match.Groups[1].Value
        $toolCount = [double]$match.Groups[2].Value

        # Exclude non-tool entries
        if ($toolName -notin @("Category", "Total", "Successful", "Failed", "MCP")) {
            $result.ToolUsage[$toolName] = $toolCount
        }
    }

    return $result
}

function Get-SummarizeJobOutput {
    <#
    .SYNOPSIS
    Gets the output from the summarize job which contains the evaluation summary.
    #>
    param(
        [string]$Repo,
        [string]$RunId
    )

    # Get the run logs for the summarize job
    $tempDir = Join-Path $env:TEMP "gh-run-$RunId"

    try {
        # Download logs
        gh run download $RunId --repo $Repo --dir $tempDir --pattern "evaluation-summary*" 2>&1 | Out-Null

        if (Test-Path $tempDir) {
            $summaryFiles = Get-ChildItem -Path $tempDir -Filter "*.md" -Recurse
            if ($summaryFiles) {
                return Get-Content $summaryFiles[0].FullName -Raw
            }
        }
    }
    catch {
        Write-Log "Could not download summary artifact: $_" -Level Warning
    }
    finally {
        if (Test-Path $tempDir) {
            Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    return $null
}

function Get-JobStepSummary {
    <#
    .SYNOPSIS
    Attempts to get the job step summary from GitHub API.
    #>
    param(
        [string]$Repo,
        [string]$RunId
    )

    try {
        # Get all jobs for the run
        $jobsResponse = gh api "repos/$Repo/actions/runs/$RunId/jobs?per_page=100" 2>&1
        if ($LASTEXITCODE -ne 0) {
            return $null
        }

        $jobs = ($jobsResponse | ConvertFrom-Json).jobs

        # Look for the summarize job
        $summarizeJob = $jobs | Where-Object { $_.name -like "*summarize*" -or $_.name -like "*summary*" }

        if ($summarizeJob) {
            # Try to get the job logs
            $logs = gh run view $RunId --repo $Repo --job $summarizeJob.id --log 2>&1
            if ($LASTEXITCODE -eq 0) {
                return $logs
            }
        }

        # If no summarize job, check for annotations or step outputs
        foreach ($job in $jobs) {
            $annotations = gh api "repos/$Repo/check-runs/$($job.id)/annotations" 2>&1
            if ($LASTEXITCODE -eq 0 -and $annotations) {
                return $annotations
            }
        }
    }
    catch {
        Write-Log "Error fetching job step summary: $_" -Level Warning
    }

    return $null
}

# Main execution
Write-Log "Fetching workflow runs from $Repository..." -Level Info

try {
    if ($RunId) {
        # Fetch specific run
        $runs = @([PSCustomObject]@{ databaseId = $RunId })
    }
    else {
        # Fetch recent runs
        $runs = Get-WorkflowRuns -Repo $Repository -WorkflowFile $Workflow -Limit $Last -BranchFilter $Branch -StatusFilter $Status
    }

    if (-not $runs -or $runs.Count -eq 0) {
        Write-Log "No workflow runs found matching criteria" -Level Warning
        exit 0
    }

    Write-Log "Found $($runs.Count) run(s) to process" -Level Success

    $allResults = @()

    foreach ($run in $runs) {
        $currentRunId = $run.databaseId
        Write-Log "`nProcessing run $currentRunId..." -Level Info

        if ($run.displayTitle) {
            Write-Log "  Title: $($run.displayTitle)" -Level Info
        }
        if ($run.headBranch) {
            Write-Log "  Branch: $($run.headBranch)" -Level Info
        }
        if ($run.conclusion) {
            Write-Log "  Conclusion: $($run.conclusion)" -Level Info
        }

        # Try to get the summary from artifacts first
        $summaryText = Get-SummarizeJobOutput -Repo $Repository -RunId $currentRunId

        # If no artifact, try to get from job logs
        if (-not $summaryText) {
            $summaryText = Get-JobStepSummary -Repo $Repository -RunId $currentRunId
        }

        if ($summaryText) {
            $parsed = Parse-EvaluationSummary -SummaryText $summaryText
            $parsed | Add-Member -NotePropertyName "RunId" -NotePropertyValue $currentRunId
            $parsed | Add-Member -NotePropertyName "RunUrl" -NotePropertyValue $run.url
            $parsed | Add-Member -NotePropertyName "Branch" -NotePropertyValue $run.headBranch
            $parsed | Add-Member -NotePropertyName "CreatedAt" -NotePropertyValue $run.createdAt

            $allResults += $parsed

            # Display summary
            Write-Log "`n  === Evaluation Summary ===" -Level Success
            Write-Log "  Model: $($parsed.Model)" -Level Info
            Write-Log "  Category: $($parsed.Category)" -Level Info
            Write-Log "  Total Entries: $($parsed.TotalEntries)" -Level Info
            Write-Log "  Successful: $($parsed.SuccessfulEvaluations) ✅" -Level Success
            Write-Log "  Failed: $($parsed.FailedEvaluations) ❌" -Level $(if ($parsed.FailedEvaluations -gt 0) { "Error" } else { "Success" })

            if ($parsed.FailedInstances.Count -gt 0) {
                Write-Log "`n  Failed Instances:" -Level Warning
                foreach ($instance in $parsed.FailedInstances) {
                    Write-Log "    - $($instance.InstanceId) ($($instance.Project)): $($instance.ErrorMessage)" -Level Warning
                }
            }

            if ($parsed.ToolUsage.Count -gt 0) {
                Write-Log "`n  Tool Usage:" -Level Info
                foreach ($tool in $parsed.ToolUsage.GetEnumerator() | Sort-Object Value -Descending) {
                    Write-Log "    $($tool.Key): $($tool.Value)" -Level Info
                }
            }
        }
        else {
            Write-Log "  Could not retrieve summary for run $currentRunId" -Level Warning

            # At minimum, show job-level failures
            $jobs = Get-JobSummary -Repo $Repository -RunId $currentRunId
            $failedJobs = $jobs | Where-Object { $_.conclusion -eq "failure" }

            if ($failedJobs) {
                Write-Log "  Failed jobs: $($failedJobs.Count)" -Level Error
                foreach ($job in $failedJobs) {
                    Write-Log "    - $($job.name): $($job.conclusion)" -Level Warning
                }
            }
        }
    }

    # Return results for pipeline use
    if ($allResults.Count -gt 0) {
        return $allResults
    }
}
catch {
    Write-Log "Error: $_" -Level Error
    Write-Log $_.ScriptStackTrace -Level Error
    exit 1
}
