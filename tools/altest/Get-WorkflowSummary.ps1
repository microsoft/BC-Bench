using module .\BCBenchUtils.psm1

<#
    .SYNOPSIS
    Gets evaluation summary from GitHub Actions workflow runs and downloads JSONL files (even if embedded in zip files).

    .DESCRIPTION
    Fetches workflow run summaries from the copilot-evaluation.yml workflow and extracts
    failure information including instance IDs, projects, and error messages.

    Additionally:
    - Downloads run artifacts
    - Locates .jsonl files (either directly in artifacts OR inside .zip files)
    - Optionally copies discovered JSONL files into a stable output folder

    .PARAMETER RunId
    Optional specific run ID to fetch. If not provided, fetches the most recent run(s).

    .PARAMETER Last
    Number of recent runs to fetch (default: 1). Ignored if RunId is specified.

    .PARAMETER Branch
    Filter runs by branch name.

    .PARAMETER Status
    Filter runs by status (completed, in_progress, queued, etc.)

    .PARAMETER Repository
    GitHub repo in OWNER/REPO format (default: microsoft/BC-Bench).

    .PARAMETER Workflow
    Workflow file name (default: copilot-evaluation.yml).

    .PARAMETER DownloadJsonl
    If true (default), downloads artifacts and searches for jsonl (including inside zip).

    .PARAMETER JsonlOutputRoot
    If provided, copies all found jsonl files into subfolders per runId for easy access.

    .PARAMETER KeepArtifacts
    If set, does not delete temp artifact download folders (useful for debugging).
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
    [string]$Workflow = "copilot-evaluation.yml",

    [Parameter(Mandatory = $false)]
    [bool]$DownloadJsonl = $true,

    [Parameter(Mandatory = $false)]
    [string]$JsonlOutputRoot,

    [Parameter(Mandatory = $false)]
    [switch]$KeepArtifacts,

    [Parameter(Mandatory = $false)]
    [string]$Category
)

function Invoke-WithRetry {
    param(
        [scriptblock]$ScriptBlock,
        [int]$MaxRetries = 3,
        [int]$BaseDelaySec = 2
    )

    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        try {
            return & $ScriptBlock
        }
        catch {
            if ($attempt -eq $MaxRetries) { throw }
            $delay = $BaseDelaySec * [math]::Pow(2, $attempt - 1)
            Write-Log "  Attempt $attempt failed, retrying in ${delay}s..." -Level Warning
            Start-Sleep -Seconds $delay
        }
    }
}

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

    if ($BranchFilter) { $args += @("--branch", $BranchFilter) }
    if ($StatusFilter) { $args += @("--status", $StatusFilter) }

    $result = gh @args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to fetch workflow runs: $result"
    }

    return $result | ConvertFrom-Json
}

function Get-RunDetails {
    param(
        [string]$Repo,
        [string]$RunId
    )

    return Invoke-WithRetry {
        $json = gh run view $RunId --repo $Repo --json "databaseId,displayTitle,conclusion,status,createdAt,headBranch,url" 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to fetch run details for run $RunId`: $json"
        }
        $json | ConvertFrom-Json
    }
}

function Get-JobSummary {
    param(
        [string]$Repo,
        [string]$RunId
    )

    return Invoke-WithRetry {
        $jobs = gh run view $RunId --repo $Repo --json jobs 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to fetch jobs for run $RunId`: $jobs"
        }
        ($jobs | ConvertFrom-Json).jobs
    }
}

function Get-SummarizeJobOutput {
    <#
    .SYNOPSIS
    Gets the output from an artifact containing the evaluation summary markdown.
    #>
    param(
        [string]$Repo,
        [string]$RunId
    )

    $tempDir = Join-Path $env:TEMP "gh-run-$RunId-summary"

    try {
        gh run download $RunId --repo $Repo --dir $tempDir --pattern "evaluation-summary*" 2>&1 | Out-Null

        if (Test-Path $tempDir) {
            $summaryFiles = Get-ChildItem -Path $tempDir -Filter "*.md" -Recurse -ErrorAction SilentlyContinue
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
    Fallback: fetches run logs (may be large). Useful if summary artifact isn't present.
    #>
    param(
        [string]$Repo,
        [string]$RunId
    )

    try {
        $logs = gh run view $RunId --repo $Repo --log 2>&1
        if ($LASTEXITCODE -eq 0 -and $logs) { return $logs }
    }
    catch {
        Write-Log "Error fetching job logs: $_" -Level Warning
    }

    return $null
}

function Parse-EvaluationSummary {
    <#
    .SYNOPSIS
    Parses the evaluation summary markdown/log text to extract failure information.
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

    if ($SummaryText -match "Total entries processed:\s*(\d+),\s*using\s+(.+)") {
        $result.TotalEntries = [int]$Matches[1]
        $result.Model = $Matches[2].Trim()
    }

    if ($SummaryText -match "Category:\s*(.+)") {
        $result.Category = $Matches[1].Trim()
    }

    if ($SummaryText -match "Successful evaluations:\s*(\d+)") {
        $result.SuccessfulEvaluations = [int]$Matches[1]
    }

    if ($SummaryText -match "Failed evaluations:\s*(\d+)") {
        $result.FailedEvaluations = [int]$Matches[1]
    }

    # Markdown table format:
    # Instance ID | Project | Status | Error Message
    $tablePattern = "(?m)^([a-zA-Z0-9_]+__[a-zA-Z0-9-]+)\s*\|\s*([^\|]+)\s*\|\s*❌\s*Failed\s*\|\s*(.+)$"
    $matches = [regex]::Matches($SummaryText, $tablePattern)

    foreach ($match in $matches) {
        $result.FailedInstances += [PSCustomObject]@{
            InstanceId   = $match.Groups[1].Value.Trim()
            Project      = $match.Groups[2].Value.Trim()
            ErrorMessage = $match.Groups[3].Value.Trim()
        }
    }

    # Alternative whitespace format (fallback)
    if ($result.FailedInstances.Count -eq 0) {
        $altPattern = "(?m)^([^\s\t]+)\s+([^\s\t]+)\s+❌\s*Failed\s+(.+)$"
        $matches = [regex]::Matches($SummaryText, $altPattern)

        foreach ($match in $matches) {
            $result.FailedInstances += [PSCustomObject]@{
                InstanceId   = $match.Groups[1].Value.Trim()
                Project      = $match.Groups[2].Value.Trim()
                ErrorMessage = $match.Groups[3].Value.Trim()
            }
        }
    }

    # Tool usage lines like: toolName: 1.0
    $toolPattern = "(?m)^(\w+):\s*([\d.]+)$"
    $toolMatches = [regex]::Matches($SummaryText, $toolPattern)

    foreach ($match in $toolMatches) {
        $toolName = $match.Groups[1].Value
        $toolCount = [double]$match.Groups[2].Value

        if ($toolName -notin @("Category", "Total", "Successful", "Failed", "MCP")) {
            $result.ToolUsage[$toolName] = $toolCount
        }
    }

    return $result
}

function Download-RunArtifacts {
    <#
    .SYNOPSIS
    Downloads all artifacts for a run into a destination folder using gh run download.
    #>
    param(
        [string]$Repo,
        [string]$RunId,
        [string]$Destination
    )

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $result = gh run download $RunId --repo $Repo --dir $Destination 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to download artifacts for run $RunId`: $result"
    }
}

function Expand-ZipsRecursively {
    <#
    .SYNOPSIS
    Expands all zip files found under Root into sibling folders (zipname_extracted), recursively.
    #>
    param(
        [string]$Root
    )

    $expandedAny = $false

    while ($true) {
        $zips = Get-ChildItem -Path $Root -Recurse -Filter *.zip -ErrorAction SilentlyContinue
        if (-not $zips -or $zips.Count -eq 0) { break }

        $didExpand = $false
        foreach ($zip in $zips) {
            $dest = Join-Path $zip.Directory.FullName ($zip.BaseName + "_extracted")
            if (Test-Path $dest) { continue }

            try {
                Expand-Archive -Path $zip.FullName -DestinationPath $dest -Force
                $didExpand = $true
                $expandedAny = $true
            }
            catch {
                Write-Log "Failed to expand zip $($zip.FullName): $_" -Level Warning
            }
        }

        if (-not $didExpand) { break }
    }

    return $expandedAny
}

function Get-JsonlFilesFromDownloadedArtifacts {
    <#
    .SYNOPSIS
    Finds .jsonl files in a downloaded artifact folder. Also expands any .zip files and searches again.
    #>
    param(
        [string]$ArtifactsRoot
    )

    # First pass: maybe jsonl is directly present
    $jsonl = Get-ChildItem -Path $ArtifactsRoot -Recurse -Filter *.jsonl -ErrorAction SilentlyContinue

    # If none, expand zips and search again
    if (-not $jsonl -or $jsonl.Count -eq 0) {
        $expanded = Expand-ZipsRecursively -Root $ArtifactsRoot
        if ($expanded) {
            $jsonl = Get-ChildItem -Path $ArtifactsRoot -Recurse -Filter *.jsonl -ErrorAction SilentlyContinue
        }
    }

    return $jsonl
}

function Copy-JsonlToOutputRoot {
    param(
        [System.IO.FileInfo[]]$JsonlFiles,
        [string]$OutputRoot,
        [string]$RunId
    )

    if (-not $OutputRoot) { return $null }

    $target = Join-Path $OutputRoot ("run-" + $RunId)
    New-Item -ItemType Directory -Force -Path $target | Out-Null

    $copied = @()
    foreach ($f in $JsonlFiles) {
        $name = $f.Name
        $dest = Join-Path $target $name

        # Avoid name collisions
        $i = 1
        while (Test-Path $dest) {
            $dest = Join-Path $target ("{0}_{1}{2}" -f [IO.Path]::GetFileNameWithoutExtension($name), $i, [IO.Path]::GetExtension($name))
            $i++
        }

        Copy-Item -Path $f.FullName -Destination $dest -Force
        $copied += Get-Item $dest
    }

    return $copied
}

# -----------------------
# Main execution
# -----------------------
Write-Log "Fetching workflow runs from $Repository..." -Level Info

try {
    if ($RunId) {
        # Fetch full run details so url/branch/createdAt are not null
        $runDetails = Get-RunDetails -Repo $Repository -RunId $RunId
        $runs = @($runDetails)
    }
    else {
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

        if ($run.conclusion -in @("cancelled", "skipped")) {
            Write-Log "Skipping run $currentRunId because conclusion is $($run.conclusion)" -Level Warning
            continue
        }

        Write-Log "`nProcessing run $currentRunId..." -Level Info

        if ($run.displayTitle) { Write-Log "  Title: $($run.displayTitle)" -Level Info }
        if ($run.headBranch) { Write-Log "  Branch: $($run.headBranch)" -Level Info }
        if ($run.conclusion) { Write-Log "  Conclusion: $($run.conclusion)" -Level Info }

        # -----------------------
        # Download JSONL from ZIP inside artifacts
        # -----------------------
        $jsonlFiles = @()
        $jsonlCopied = @()
        $artifactsDir = $null

        if ($DownloadJsonl) {
            $artifactsDir = Join-Path $env:TEMP ("bcbench-artifacts-" + $currentRunId)
            if (Test-Path $artifactsDir) {
                Remove-Item $artifactsDir -Recurse -Force -ErrorAction SilentlyContinue
            }

            Write-Log "  Downloading artifacts for run $currentRunId..." -Level Info
            try {
                Download-RunArtifacts -Repo $Repository -RunId $currentRunId -Destination $artifactsDir
            }
            catch {
                Write-Log "No artifacts for run $currentRunId, continuing..." -Level Warning
                $jsonlFiles = @()
            }

            $jsonlFiles = Get-JsonlFilesFromDownloadedArtifacts -ArtifactsRoot $artifactsDir

            if ($jsonlFiles -and $jsonlFiles.Count -gt 0) {
                Write-Log "  Found JSONL files: $($jsonlFiles.Count)" -Level Success

                if ($JsonlOutputRoot) {
                    New-Item -ItemType Directory -Force -Path $JsonlOutputRoot | Out-Null
                    $jsonlCopied = Copy-JsonlToOutputRoot -JsonlFiles $jsonlFiles -OutputRoot $JsonlOutputRoot -RunId $currentRunId
                    Write-Log "  Copied JSONL files to: $(Join-Path $JsonlOutputRoot ('run-' + $currentRunId))" -Level Success
                }
                else {
                    $jsonlFiles | Select-Object -First 2 | ForEach-Object {
                        Write-Log "    JSONL: $($_.FullName)" -Level Info
                    }
                }
            }
            else {
                Write-Log "  No JSONL files found in artifacts (even after expanding zips)." -Level Warning
            }
        }

        # -----------------------
        # Existing: retrieve summary
        # -----------------------
        $summaryText = Get-SummarizeJobOutput -Repo $Repository -RunId $currentRunId
        if (-not $summaryText) {
            $summaryText = Get-JobStepSummary -Repo $Repository -RunId $currentRunId
        }

        if ($summaryText) {
            $parsed = Parse-EvaluationSummary -SummaryText $summaryText
            # ✅ Category filter
            if ($Category) {
                if (-not $parsed.Category) {
                    Write-Log "Skipping run $currentRunId (no category found)" -Level Warning
                    continue
                }

                if ($parsed.Category -ne $Category) {
                    Write-Log "Skipping run $currentRunId (category '$($parsed.Category)' does not match '$Category')" -Level Info
                    continue
                }
            }
            $parsed | Add-Member -NotePropertyName "RunId" -NotePropertyValue $currentRunId
            $parsed | Add-Member -NotePropertyName "RunUrl" -NotePropertyValue $run.url
            $parsed | Add-Member -NotePropertyName "Branch" -NotePropertyValue $run.headBranch
            $parsed | Add-Member -NotePropertyName "CreatedAt" -NotePropertyValue $run.createdAt

            $parsed | Add-Member -NotePropertyName "JsonlFilesCount" -NotePropertyValue ($jsonlFiles.Count)

            # PS 5.1-safe selection (instead of ??)
            $jsonlToAttach = $null
            if ($jsonlCopied -and $jsonlCopied.Count -gt 0) {
                $jsonlToAttach = $jsonlCopied.FullName
            }
            elseif ($jsonlFiles -and $jsonlFiles.Count -gt 0) {
                $jsonlToAttach = $jsonlFiles.FullName
            }

            $parsed | Add-Member -NotePropertyName "JsonlFiles" -NotePropertyValue $jsonlToAttach

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
            try {
                $jobs = Get-JobSummary -Repo $Repository -RunId $currentRunId
                $failedJobs = $jobs | Where-Object { $_.conclusion -eq "failure" }

                if ($failedJobs) {
                    Write-Log "  Failed jobs: $($failedJobs.Count)" -Level Error
                    foreach ($job in $failedJobs) {
                        Write-Log "    - $($job.name): $($job.conclusion)" -Level Warning
                    }
                }
            }
            catch {
                Write-Log "  Could not fetch job details for run $currentRunId (GitHub API error). Skipping." -Level Warning
            }
        }

        # Cleanup unless requested otherwise
        if ($DownloadJsonl -and $artifactsDir -and (Test-Path $artifactsDir) -and (-not $KeepArtifacts)) {
            Remove-Item $artifactsDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        elseif ($DownloadJsonl -and $artifactsDir -and (Test-Path $artifactsDir) -and $KeepArtifacts) {
            Write-Log "  Keeping artifacts folder: $artifactsDir" -Level Info
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
