param(
    [Parameter(Mandatory = $true)][string]$EntryRoot,
    [Parameter(Mandatory = $true)][string]$ProtectedRoot,
    [Parameter(Mandatory = $true)][string]$ContainerName
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "BugFixLifecycle.psm1") -Force -DisableNameChecking
Complete-BCBenchBugFixLifecycle -EntryRoot $EntryRoot -ProtectedRoot $ProtectedRoot -ContainerName $ContainerName
