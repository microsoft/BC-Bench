using module .\DatasetEntry.psm1
using module .\BCBenchUtils.psm1
using module .\AppUtils.psm1
using module .\BCContainerManagement.psm1

param(
    [Parameter(Mandatory=$false)]
    [string]$Version,

    [Parameter(Mandatory=$false)]
    [string]$InstanceId,

    [Parameter(Mandatory=$false)]
    [string]$DatasetPath = (Get-BCBenchDatasetPath),

    [Parameter(Mandatory=$true)]
    [string]$RepoPath,

    [Parameter(Mandatory=$false)]
    [string]$Username='admin',

    [Parameter(Mandatory=$false)]
    [SecureString]$Password
)

[DatasetEntry[]] $entries = Get-DatasetEntries -DatasetPath $DatasetPath -Version $Version -InstanceId $InstanceId
if ($InstanceId) {
    $Version = $entries[0].environment_setup_version
    Write-Log "Found version $Version for InstanceId $InstanceId" -Level Info
} else {
    Write-Log "Found $($entries.Count) dataset entries to process." -Level Info
}

Write-Log "Verifying projects build and tests run for version $Version, in $DatasetPath ..." -Level Info

[PSCredential]$credential = Get-BCCredential -Username $Username -Password $Password

Write-Log "Using provided repository path: $RepoPath" -Level Debug

if (-not (Test-Path $RepoPath)) {
    Write-Error "NAV repository not found at: $RepoPath. Please run Setup-ContainerAndRepository.ps1 first."
    exit 1
}

Import-Module BcContainerHelper -Force -DisableNameChecking

[string] $containerName = Get-StandardContainerName -Version $Version
[ValidationResult[]]$validationResults = @()

foreach ($entry in $entries) {
    Write-Log "Verifying entry: $($entry.instance_id)" -Level Info

    try {
        Push-Location $RepoPath

        Write-Log "Checking out base commit: $($entry.base_commit)" -Level Info
        $checkoutResult = git checkout $entry.base_commit 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to checkout base commit: $checkoutResult"
        }

        Write-Log "Applying test patch for $($entry.instance_id)" -Level Info
        Invoke-GitApplyPatch -PatchContent $entry.test_patch -PatchId $entry.instance_id

        Write-Log "[Test Patch Only] Building projects for $($entry.instance_id)" -Level Info
        foreach ($projectPath in $entry.project_paths) {
            [string]$fullProjectPath = Join-Path -Path $RepoPath -ChildPath $projectPath
            Update-AppProjectVersion -ProjectPath $fullProjectPath -Version $Version
            Invoke-AppBuildAndPublish -containerName $containerName -appProjectFolder $fullProjectPath -credential $credential -skipVerification -useDevEndpoint
        }
        Write-Log "[Test Patch Only] Build completed successfully for $($entry.instance_id)" -Level Success

        Write-Log "[Test Patch Only] Running FAIL_TO_PASS tests for $($entry.instance_id)" -Level Info
        Invoke-DatasetTests -containerName $containerName -credential $credential -testEntries $entry.FAIL_TO_PASS -expectation 'Fail'

        Write-Log "[Test Patch Only] Running PASS_TO_PASS tests for $($entry.instance_id)" -Level Info
        Invoke-DatasetTests -containerName $containerName -credential $credential -testEntries $entry.PASS_TO_PASS -expectation 'Pass'

        Write-Log "Applying gold patch for $($entry.instance_id)" -Level Info
        Invoke-GitApplyPatch -PatchContent $entry.patch -PatchId $entry.instance_id

        Write-Log "[Gold Patch Applied] Building projects for $($entry.instance_id)" -Level Info
        # only need to build the test project
        foreach ($projectPath in $entry.project_paths) {
            [string]$fullProjectPath = Join-Path -Path $RepoPath -ChildPath $projectPath
            Update-AppProjectVersion -ProjectPath $fullProjectPath -Version $Version
            Invoke-AppBuildAndPublish -containerName $containerName -appProjectFolder $fullProjectPath -credential $credential -skipVerification -useDevEndpoint
        }
        Write-Log "[Gold Patch Applied] Build completed successfully for $($entry.instance_id)" -Level Success

        Write-Log "[Gold Patch Applied] Running FAIL_TO_PASS tests for $($entry.instance_id)" -Level Info
        Invoke-DatasetTests -containerName $containerName -credential $credential -testEntries $entry.FAIL_TO_PASS -expectation 'Pass'

        Write-Log "[Gold Patch Applied] Running PASS_TO_PASS tests for $($entry.instance_id)" -Level Info
        Invoke-DatasetTests -containerName $containerName -credential $credential -testEntries $entry.PASS_TO_PASS -expectation 'Pass'

        Write-Log "[Gold Patch Applied] Tests passed successfully" -Level Success
        $validationResults += [ValidationResult]::new($entry.instance_id, "Passed", "")
    }
    catch {
        Write-Log "Exception while verifying $($entry.instance_id): $($_.Exception.Message)" -Level Error
        $validationResults += [ValidationResult]::new($entry.instance_id, "Failed", $_.Exception.Message)
    }
    finally {
        Write-Log "Cleaning up Git state for $($entry.instance_id)" -Level Debug
        git reset --hard HEAD 2>&1 | Out-Null
        git clean -fd 2>&1 | Out-Null
        Pop-Location
    }
}


function Show-ValidationResults {
    param(
        [Parameter(Mandatory=$true)]
        [ValidationResult[]]$Results
    )

    Write-Host "`n`n" -NoNewline
    Write-Log "========= Dataset Verification Summary =========" -Level Info

    [int] $successCount = ($Results | Where-Object { $_.Status -eq "Passed" }).Count
    [int] $failureCount = ($Results | Where-Object { $_.Status -eq "Failed" }).Count

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

    return $failureCount
}

[int] $failureCount = Show-ValidationResults -Results $validationResults

if ($failureCount -gt 0) {
    Write-Log "Dataset Verification completed with failures" -Level Error
    exit 1
} else {
    Write-Log "Dataset Verification completed successfully" -Level Success
    exit 0
}
