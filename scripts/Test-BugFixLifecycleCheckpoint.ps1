param(
    [Parameter(Mandatory)][string]$ContainerName,
    [Parameter(Mandatory)][string]$CheckpointPath,
    [ValidateRange(1, 100)][int]$Iterations = 10,
    [ValidateSet("None", "CorruptBackup", "HashMismatch", "ReadinessFailure", "UnexpectedApp",
        "MissingJUnit", "DuplicateDiscovery", "DuplicateExecution", "ServiceRestartFailure", "CleanupFailure")]
    [string]$Fault = "None"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$completed = $false
try {
    $powershell = (Get-Command pwsh -ErrorAction Stop).Source
    if ($PSVersionTable.PSVersion.Major -lt 7 -or $powershell -match '[\\/]WindowsApps[\\/]') {
        throw "Checkpoint rehearsal requires native PowerShell 7, not Store activation."
    }
    if ($ContainerName -cne $env:BC_CONTAINER_NAME) { throw "Requested container differs from setup ownership." }
    Import-Module (Join-Path $PSScriptRoot "BugFixLifecycle.psm1") -Force -DisableNameChecking
    Start-BCBenchWorkflowExecution -ProtectedRoot $env:BCBENCH_LIFECYCLE_PROTECTED_ROOT `
        -ExpectedContainerId $env:BCBENCH_LIFECYCLE_EXPECTED_CONTAINER_ID `
        -ExpectedInvocationId $env:BCBENCH_LIFECYCLE_EXPECTED_INVOCATION_ID
    uv run --frozen --no-sync python -m bcbench.commands.bugfix_rehearsal `
        --container-name $ContainerName --checkpoint-path $CheckpointPath --iterations $Iterations --fault $Fault
    if ($LASTEXITCODE -ne 0) { throw "Checkpoint rehearsal failed; inspect protected records." }
    $completed = $true
}
finally {
    if ([string]::IsNullOrWhiteSpace($env:BCBENCH_LIFECYCLE_PROTECTED_ROOT) -or [string]::IsNullOrWhiteSpace($env:BCBENCH_LIFECYCLE_ENTRY_ROOT)) {
        throw "No allocated ownership roots are available for rehearsal finalization."
    }
    try {
        & (Join-Path $PSScriptRoot "Complete-BugFixLifecycle.ps1") `
            -EntryRoot $env:BCBENCH_LIFECYCLE_ENTRY_ROOT -ProtectedRoot $env:BCBENCH_LIFECYCLE_PROTECTED_ROOT `
            -ContainerName $env:BC_CONTAINER_NAME -TimeoutSeconds 180 `
            -InjectContainerRemovalFailure:($completed -and $Fault -eq "CleanupFailure")
        if ($completed -and $Fault -eq "CleanupFailure") { throw "Injected cleanup fault was not detected." }
    }
    catch {
        if ($completed -and $Fault -eq "CleanupFailure") {
            uv run --frozen --no-sync python -m bcbench.commands.bugfix_rehearsal `
                --verify-cleanup-fault $env:BCBENCH_LIFECYCLE_PROTECTED_ROOT
            if ($LASTEXITCODE -ne 0) { throw "Cleanup failed for an unexpected reason; quarantine retained." }
        }
        throw
    }
}
