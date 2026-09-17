param(
    [Parameter(Mandatory = $true)]
    [string]$InstanceId,

    [ValidateSet("bug-fix")]
    [string]$Category = "bug-fix",

    [string]$DatasetPath,

    [string]$Version,

    [string]$Country = "w1",

    [string]$ContainerName,

    [Parameter(Mandatory = $true)]
    [string]$EvaluatorUsername,

    [Parameter(Mandatory = $true)]
    [SecureString]$EvaluatorPassword,

    [string]$EntryRoot,

    [string]$ProtectedRoot,

    [string[]]$ToolRoots = @(),

    [switch]$AlMcp,

    [switch]$BcMcp,

    [string]$GithubToken,

    [string]$AdoToken
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "BCBenchUtils.psm1") -Force -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot "BugFixLifecycle.psm1") -Force -DisableNameChecking

if ([string]::IsNullOrEmpty($DatasetPath)) {
    $DatasetPath = Get-BCBenchDatasetPath -Category $Category
}

$safeInstanceName = ($InstanceId -replace "[^A-Za-z0-9_.-]", "-").Trim("-", ".")
if ([string]::IsNullOrEmpty($safeInstanceName)) {
    throw "InstanceId does not contain any characters valid for lifecycle paths."
}
if ($safeInstanceName.Length -gt 80) {
    $safeInstanceName = $safeInstanceName.Substring(0, 80)
}
if ([string]::IsNullOrEmpty($ContainerName)) {
    $containerSuffix = $safeInstanceName.ToLowerInvariant()
    if ($containerSuffix.Length -gt 40) {
        $containerSuffix = $containerSuffix.Substring(0, 40)
    }
    $ContainerName = "bcbench-$containerSuffix"
}
if ([string]::IsNullOrEmpty($EntryRoot)) {
    $EntryRoot = Join-Path "C:\bcbench\entries" $safeInstanceName
}
if ([string]::IsNullOrEmpty($ProtectedRoot)) {
    $ProtectedRoot = Join-Path "C:\bcbench-protected" $safeInstanceName
}

[System.Collections.Generic.List[string]]$effectiveToolRoots = [System.Collections.Generic.List[string]]::new()
$effectiveToolRoots.Add((Split-Path $PSScriptRoot -Parent))
foreach ($commandName in @("pwsh", "python", "git", "docker", "dotnet")) {
    $command = Get-Command $commandName -ErrorAction SilentlyContinue
    if ($null -ne $command -and -not [string]::IsNullOrEmpty($command.Source)) {
        $effectiveToolRoots.Add((Split-Path $command.Source -Parent))
    }
}
foreach ($toolRoot in $ToolRoots) {
    $effectiveToolRoots.Add($toolRoot)
}

try {
    Invoke-BCBenchBugFixLifecycle `
        -InstanceId $InstanceId `
        -Category $Category `
        -DatasetPath $DatasetPath `
        -Version $Version `
        -Country $Country `
        -ContainerName $ContainerName `
        -EvaluatorUsername $EvaluatorUsername `
        -EvaluatorPassword $EvaluatorPassword `
        -EntryRoot $EntryRoot `
        -ProtectedRoot $ProtectedRoot `
        -ToolRoots @($effectiveToolRoots | Select-Object -Unique) `
        -AlMcp:$AlMcp `
        -BcMcp:$BcMcp `
        -GithubToken $GithubToken `
        -AdoToken $AdoToken | Out-Null
}
catch {
    throw "Setup-BugFixLifecycle failed for '$InstanceId': $($_.Exception.Message)"
}
