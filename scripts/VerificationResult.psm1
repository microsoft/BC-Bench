using module .\BCBenchUtils.psm1

class VerificationResult {
    [string]$InstanceId
    [string]$Version
    [string]$Status      # "Passed" or "Failed"
    [string]$Message
    [datetime]$Timestamp

    VerificationResult([string]$instanceId, [string]$version, [string]$status, [string]$message) {
        $this.InstanceId = $instanceId
        $this.Version = $version
        $this.Status = $status
        $this.Message = $message
        $this.Timestamp = Get-Date
    }

    [void] Save([string]$outputDir, [string]$fileName) {
        if (-not (Test-Path $outputDir)) {
            New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
        }

        $outputFile = Join-Path -Path $outputDir -ChildPath $fileName
        $resultDict = $this.ToHashtable()
        $jsonLine = $resultDict | ConvertTo-Json -Compress

        Add-Content -Path $outputFile -Value $jsonLine -Encoding UTF8
        Write-Log "Saved verification result for $($this.InstanceId) to $outputFile" -Level Info
    }

    # Convert to hashtable for JSON export
    [hashtable] ToHashtable() {
        return @{
            instance_id = $this.InstanceId
            version = $this.Version
            status = $this.Status
            message = $this.Message
            timestamp = $this.Timestamp.ToString("o")
        }
    }
}

<#
.SYNOPSIS
    Read verification results from JSONL file(s)
.DESCRIPTION
    Searches for all files matching the result file pattern in the results directory
    and its subdirectories, aggregating results from all found files.
.PARAMETER ResultsDir
    Directory containing verification result files
.PARAMETER ResultPattern
    File pattern to match (default: instance_results.jsonl)
.OUTPUTS
    Array of VerificationResult objects
.EXAMPLE
    $results = Read-VerificationResults -ResultsDir "C:\results"
#>
function Read-VerificationResults {
    [CmdletBinding()]
    [OutputType([VerificationResult[]])]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResultsDir,

        [Parameter(Mandatory = $false)]
        [string]$ResultPattern = "*.jsonl"
    )

    [VerificationResult[]]$results = @()

    if (-not (Test-Path $ResultsDir)) {
        Write-Log "Results directory not found: $ResultsDir" -Level Warning
        return $results
    }

    $resultFiles = Get-ChildItem -Path $ResultsDir -Filter $ResultPattern -Recurse -File

    if ($resultFiles.Count -eq 0) {
        Write-Log "No results files matching '$ResultPattern' found in $ResultsDir" -Level Warning
        return $results
    }

    Write-Log "Found $($resultFiles.Count) result file(s) to process" -Level Info

    foreach ($resultFile in $resultFiles) {
        Write-Log "Reading results from: $($resultFile.FullName)" -Level Debug

        $content = Get-Content -Path $resultFile.FullName -Encoding UTF8
        foreach ($line in $content) {
            if ([string]::IsNullOrWhiteSpace($line)) {
                continue
            }

            try {
                $data = $line | ConvertFrom-Json
                $result = [VerificationResult]::new(
                    $data.instance_id,
                    $data.version,
                    $data.status,
                    $data.message
                )
                # Restore timestamp from saved data
                if ($data.timestamp) {
                    $result.Timestamp = [datetime]::Parse($data.timestamp)
                }
                $results += $result
            }
            catch {
                Write-Log "Failed to parse result line: $line - Error: $_" -Level Warning
            }
        }
    }

    Write-Log "Successfully loaded $($results.Count) verification result(s)" -Level Info
    return $results
}

<#
.SYNOPSIS
    Generate and display summary of verification results
.DESCRIPTION
    Analyzes verification results and generates a summary report.
    Automatically writes to GitHub Actions step summary if running in CI.
.PARAMETER Results
    Array of VerificationResult objects to summarize
.OUTPUTS
    Returns the number of failed verifications
.EXAMPLE
    $failureCount = Show-VerificationSummary -Results $results
#>
function Show-VerificationSummary {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [VerificationResult[]]$Results
    )

    if ($Results.Count -eq 0) {
        Write-Log "No verification results to summarize" -Level Warning
        return 0
    }

    Write-Host "`n`n" -NoNewline
    Write-Log "========= Dataset Verification Summary =========" -Level Info

    [int]$successCount = ($Results | Where-Object { $_.Status -eq "Passed" }).Count
    [int]$failureCount = ($Results | Where-Object { $_.Status -eq "Failed" }).Count

    Write-Log "Total entries processed: $($Results.Count)" -Level Info
    Write-Log "Successful verifications: $successCount" -Level Success
    Write-Log "Failed verifications: $failureCount" -Level $(if ($failureCount -gt 0) { "Error" } else { "Info" })

    $Results | Where-Object { $_.Status -eq "Failed" } | ForEach-Object {
        if ($env:CI) {
            Write-Host "::error title=Dataset Verification::Instance ID: $($_.InstanceId) - Message: $($_.Message)"
        } else {
            Write-Log "Instance ID: $($_.InstanceId) - Message: $($_.Message)" -Level Error
        }
    }

    if ($env:GITHUB_STEP_SUMMARY) {
        Write-Log "Writing results to GitHub Actions job summary" -Level Info

        $successIcon = if ($failureCount -eq 0) { ":white_check_mark:" } else { ":x:" }
        $summary = @"
Total entries processed: **$($Results.Count)**
- Successful verifications: $successCount :white_check_mark:
- Failed verifications: $failureCount $successIcon

## Detailed Results

| Instance ID | Version | Status | Message |
|-------------|---------|--------|---------|
"@

        foreach ($result in $Results) {
            $statusIcon = if ($result.Status -eq "Passed") { ":white_check_mark:" } else { ":x:" }
            # Escape pipe characters in messages to prevent table breaking
            $escapedMessage = $result.Message -replace '\|', '\|'
            $summary += "`n| ``$($result.InstanceId)`` | ``$($result.Version)`` | $statusIcon $($result.Status) | $escapedMessage |"
        }

        $summary | Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Encoding utf8 -Append
    }

    if ($failureCount -gt 0) {
        Write-Log "Dataset verification completed with failures." -Level Error
        throw "Verification failed for $failureCount instance(s)."
    } else {
        Write-Log "Dataset verification completed successfully with no failures." -Level Success
    }
}

Export-ModuleMember -Function Read-VerificationResults, Show-VerificationSummary
