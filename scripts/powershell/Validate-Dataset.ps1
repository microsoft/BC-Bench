using module .\DatasetEntry.psm1
using module .\BCBenchUtils.psm1
using module .\AppUtils.psm1

param(
    [Parameter(Mandatory=$true)]
    [string]$Version,

    [Parameter(Mandatory=$false)]
    [string]$DatasetPath = "$PSScriptRoot\..\..\dataset\bcbench_nav.jsonl",

    [Parameter(Mandatory=$false)]
    [string]$NAVClonePath,

    [Parameter(Mandatory=$false)]
    [string]$Username='admin',

    [Parameter(Mandatory=$false)]
    [SecureString]$Password
)

Write-Log "Running BC Bench Dataset Validation for version $Version, , Dataset Path: $DatasetPath ..." -Level Info

[PSCredential]$credential = Get-BCCredential -Username $Username -Password $Password

if (-not $NAVClonePath) {
    $NAVClonePath = Join-Path -Path $env:TEMP -ChildPath "NAV-$Version"
    Write-Log "Using default NAV clone path: $NAVClonePath" -Level Info
} else {
    Write-Log "Using provided NAV clone path: $NAVClonePath" -Level Info
}

if (-not (Test-Path $NAVClonePath)) {
    Write-Error "NAV repository not found at: $NAVClonePath. Please run Setup-ValidationEnvironment.ps1 first."
    exit 1
}

Write-Log "Loading dataset entries for version $Version..." -Level Info
try {
    [DatasetEntry[]] $entries = Get-DatasetEntries -DatasetPath $DatasetPath
    [DatasetEntry[]] $versionEntries = $entries | Where-Object { $_.environment_setup_version -eq $Version }

    if ($versionEntries.Count -eq 0) {
        Write-Log "No dataset entries found for version $Version" -Level Warning
        exit 0
    }

    Write-Log "Found $($versionEntries.Count) entries for version $Version" -Level Info
}
catch {
    Write-Error "Failed to load dataset entries: $($_.Exception.Message)"
    exit 1
}

[string] $containerName = Get-StandardContainerName -Version $Version
[ValidationResult[]]$validationResults = @()
[int]$successCount = 0
[int]$failureCount = 0

foreach ($entry in $versionEntries) {
    Write-Log "Validating entry: $($entry.instance_id)" -Level Info

    try {
        Push-Location $NAVClonePath

        Write-Log "Checking out base commit: $($entry.base_commit)" -Level Info
        $checkoutResult = git checkout $entry.base_commit 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to checkout base commit: $checkoutResult"
        }

        Write-Log "Applying test patch for $($entry.instance_id)" -Level Info
        Invoke-GitApplyPatch -PatchContent $entry.test_patch -PatchId $entry.instance_id

        Write-Log "[Test Patch Only] Building projects for $($entry.instance_id)" -Level Info
        foreach ($projectPath in $entry.project_paths) {
            [string]$fullProjectPath = Join-Path -Path $NAVClonePath -ChildPath $projectPath
            Update-AppProjectVersion -ProjectPath $fullProjectPath -Version $Version
            Invoke-AppBuildAndPublish -containerName $containerName -appProjectFolder $fullProjectPath -credential $credential -skipVerification
        }
        Write-Log "[Test Patch Only] Build completed successfully for $($entry.instance_id)" -Level Success

        Write-Log "[Test Patch Only] Running FAIL_TO_PASS tests for $($entry.instance_id)" -Level Info
        Invoke-DatasetTests -containerName $containerName -credential $credential -testEntries $entry.FAIL_TO_PASS -expectation 'Fail'

        Write-Log "Applying gold patch for $($entry.instance_id)" -Level Info
        Invoke-GitApplyPatch -PatchContent $entry.patch -PatchId $entry.instance_id

        Write-Log "[Gold Patch Applied] Building projects for $($entry.instance_id)" -Level Info
        # only need to build the test project
        foreach ($projectPath in $entry.project_paths) {
            [string]$fullProjectPath = Join-Path -Path $NAVClonePath -ChildPath $projectPath
            Update-AppProjectVersion -ProjectPath $fullProjectPath -Version $Version
            Invoke-AppBuildAndPublish -containerName $containerName -appProjectFolder $fullProjectPath -credential $credential -skipVerification
        }
        Write-Log "[Gold Patch Applied] Build completed successfully for $($entry.instance_id)" -Level Success

        Write-Log "[Gold Patch Applied] Running FAIL_TO_PASS tests for $($entry.instance_id)" -Level Info
        Invoke-DatasetTests -containerName $containerName -credential $credential -testEntries $entry.FAIL_TO_PASS -expectation 'Pass'

        Write-Log "[Gold Patch Applied] Tests passed successfully" -Level Success
        $validationResults += [ValidationResult]::new($entry.instance_id, "Passed", "All tests passed after applying patch")
        $successCount++
    }
    catch {
        Write-Log "Exception while validating $($entry.instance_id): $($_.Exception.Message)" -Level Error
        $validationResults += [ValidationResult]::new($entry.instance_id, "Failed", $_.Exception.Message)
        $failureCount++
    }
    finally {
        Write-Log "Cleaning up Git state for $($entry.instance_id)" -Level Debug
        git reset --hard HEAD 2>&1 | Out-Null
        git clean -fd 2>&1 | Out-Null
        Pop-Location
    }
}

# Summary
Write-Host "`n" -NoNewline
Write-Log "=== Validation Summary ===" -Level Info
Write-Log "Total entries processed: $($versionEntries.Count)" -Level Info
Write-Log "Successful validations: $successCount" -Level Success
Write-Log "Failed validations: $failureCount" -Level $(if ($failureCount -gt 0) { "Error" } else { "Info" })

if ($env:RUNNER_DEBUG -eq '1') {
    Write-Host "`n" -NoNewline
    Write-Log "Detailed Results:" -Level Warning
    $validationResults | Format-Table -Property InstanceId, Status, Message -AutoSize
}

# Exit with appropriate code
if ($failureCount -gt 0) {
    Write-Log "Dataset validation completed with failures" -Level Error
    exit 1
} else {
    Write-Log "Dataset validation completed successfully" -Level Success
    exit 0
}