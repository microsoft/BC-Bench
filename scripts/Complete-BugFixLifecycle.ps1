param(
    [Parameter(Mandatory = $true)][string]$EntryRoot,
    [Parameter(Mandatory = $true)][string]$ProtectedRoot,
    [Parameter(Mandatory = $true)][string]$ContainerName,
    [ValidateRange(1, 3600)][int]$TimeoutSeconds = 180,
    [Parameter(DontShow = $true)][switch]$Worker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($Worker) {
    Import-Module (Join-Path $PSScriptRoot "BugFixLifecycle.psm1") -Force -DisableNameChecking
    Complete-BCBenchBugFixLifecycle -EntryRoot $EntryRoot -ProtectedRoot $ProtectedRoot -ContainerName $ContainerName
}
else {
    uv run --frozen --no-sync bcbench bugfix-lifecycle cleanup --entry-root $EntryRoot `
        --protected-root $ProtectedRoot --container-name $ContainerName --timeout-seconds $TimeoutSeconds
    if ($LASTEXITCODE -ne 0) { throw "Bounded workflow cleanup failed ($LASTEXITCODE)." }
}
