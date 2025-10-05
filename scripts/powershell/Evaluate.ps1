using module .\DatasetEntry.psm1
using module .\BCBenchUtils.psm1
using module .\AppUtils.psm1
using module .\BCContainerManagement.psm1

param(
    [Parameter(Mandatory=$true)]
    [string]$InstanceID,

    [Parameter(Mandatory=$false)]
    [string]$DatasetPath = "$PSScriptRoot\..\..\dataset\bcbench_nav.jsonl",

    [Parameter(Mandatory=$false)]
    [string]$NAVClonePath,

    [Parameter(Mandatory=$false)]
    [string]$Username='admin',

    [Parameter(Mandatory=$false)]
    [SecureString]$Password
)

Write-Log "Evaluating generated patch for entry: $InstanceID..." -Level Info

[PSCredential]$credential = Get-BCCredential -Username $Username -Password $Password

try {
    [DatasetEntry] $entry = Get-DatasetEntry -DatasetPath $DatasetPath -InstanceId $InstanceID

    if (-not $entry) {
        Write-Error "Entry not found: $InstanceID"
        exit 1
    }

    Write-Log "Found entry: $($entry.instance_id)" -Level Success
}
catch {
    Write-Error "Failed to load entry from dataset: $($_.Exception.Message)"
    exit 1
}

if (-not $NAVClonePath) {
    $NAVClonePath = Join-Path -Path $env:TEMP -ChildPath "NAV-$version"
    Write-Log "Using default NAV repository path: $NAVClonePath" -Level Info
} else {
    Write-Log "Using provided NAV repository path: $NAVClonePath" -Level Info
}

if (-not (Test-Path $NAVClonePath)) {
    Write-Error "NAV repository not found at: $NAVClonePath. Please run Setup-ContainerAndRepository.ps1 first."
    exit 1
}

Import-Module BcContainerHelper -Force -DisableNameChecking

[string] $Version = $entry.environment_setup_version
[string] $containerName = Get-StandardContainerName -Version $Version
[ValidationResult]$validationResult = $null

Write-Log "Processing entry: $($entry.instance_id)" -Level Info

try {
    Push-Location $NAVClonePath

    Write-Log "Checking out base commit: $($entry.base_commit)" -Level Info
    $checkoutResult = git checkout $entry.base_commit 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to checkout base commit: $checkoutResult"
    }

    Write-Log "Applying test patch for $($entry.instance_id)" -Level Info
    Invoke-GitApplyPatch -PatchContent $entry.test_patch -PatchId $entry.instance_id

    Write-Log "Building and publishing projects for $($entry.instance_id)" -Level Info
    foreach ($projectPath in $entry.project_paths) {
        [string]$fullProjectPath = Join-Path -Path $NAVClonePath -ChildPath $projectPath
        Invoke-AppBuildAndPublish -containerName $containerName -appProjectFolder $fullProjectPath -credential $credential -skipVerification -useDevEndpoint
    }
    Write-Log "Build completed successfully for $($entry.instance_id)" -Level Success

    Write-Log "Running FAIL_TO_PASS tests for $($entry.instance_id)" -Level Info
    Invoke-DatasetTests -containerName $containerName -credential $credential -testEntries $entry.FAIL_TO_PASS -expectation 'Pass'

    Write-Log "Tests passed successfully - Evaluation PASSED" -Level Success
    $validationResult = [ValidationResult]::new($entry.instance_id, "Passed", "All tests passed after applying generated patch")
}
catch {
    Write-Log "Exception during evaluation of $($entry.instance_id): $($_.Exception.Message)" -Level Error
    $validationResult = [ValidationResult]::new($entry.instance_id, "Failed", $_.Exception.Message)
}
finally {
    Write-Log "Cleaning up Git state for $($entry.instance_id)" -Level Debug
    git reset --hard HEAD 2>&1 | Out-Null
    git clean -fd 2>&1 | Out-Null
    Pop-Location
}

Write-Log "=== Evaluation Summary ===" -Level Info

if ($validationResult.Status -eq "Passed") {
    Write-Log "Status: SUCCESS" -Level Success
    Write-Log "Instance: $($validationResult.InstanceId)" -Level Info
    Write-Log "Message: $($validationResult.Message)" -Level Success
    exit 0
} else {
    Write-Log "Status: FAILED" -Level Error
    Write-Log "Instance: $($validationResult.InstanceId)" -Level Info
    Write-Log "Message: $($validationResult.Message)" -Level Error
    exit 1
}
