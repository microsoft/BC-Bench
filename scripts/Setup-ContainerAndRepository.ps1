using module .\DatasetEntry.psm1
using module .\BCBenchUtils.psm1
using module .\BCContainerManagement.psm1

param(
    [Parameter(Mandatory = $false)]
    [string]$Version,

    [Parameter(Mandatory = $false)]
    [string]$InstanceId,

    [Parameter(Mandatory = $false)]
    [string]$DatasetPath = (Get-BCBenchDatasetPath),

    [Parameter(Mandatory = $false)]
    [string]$Country = "w1",

    [Parameter(Mandatory = $false)]
    [string]$ContainerName = $env:BC_CONTAINER_NAME ?? "bcbench",

    [Parameter(Mandatory = $false)]
    [string]$Username = $env:BC_CONTAINER_USERNAME ?? "admin",

    [Parameter(Mandatory = $false)]
    [SecureString]$Password,

    [Parameter(Mandatory = $false)]
    [string]$RepoPath
)

[DatasetEntry[]] $entries = Get-DatasetEntries -DatasetPath $DatasetPath -Version $Version -InstanceId $InstanceId
if ($InstanceId) {
    $Version = $entries[0].environment_setup_version
    Write-Log "Found version $Version for InstanceId $InstanceId" -Level Info
}
else {
    Write-Log "Found $($entries.Count) dataset entries to process." -Level Info
}

Write-Log "Setting up BC container and repository for version $Version, Dataset Path: $DatasetPath" -Level Info

[PSCredential]$credential = Get-BCCredential -Username $Username -Password $Password

if (-not $RepoPath) {
    $RepoPath = Join-Path -Path $env:GITHUB_WORKSPACE -ChildPath "testbed"
}
Write-Log "Using repository path: $RepoPath" -Level Info

if (Test-Path $RepoPath) {
    throw "Repository already exists at $RepoPath. This indicates the machine was not properly cleaned up from a previous run."
}

[hashtable] $cloneInfo = Get-RepoCloneInfo -Entry $entries[0]
[string] $commitSha = $entries[0].base_commit

Write-Log "Cloning repository $($entries[0].repo) to $RepoPath" -Level Info
Invoke-GitCloneWithRetry -RepoUrl $cloneInfo.Url -Token $cloneInfo.Token -ClonePath $RepoPath -CommitSha $commitSha -SparseCheckoutPaths $cloneInfo.SparseCheckoutPaths

Import-Module BcContainerHelper -Force -DisableNameChecking

Write-Log "Container name: $ContainerName" -Level Info

if (Test-ContainerExists -containerName $ContainerName) {
    throw "Container $ContainerName already exists. This indicates the machine was not properly cleaned up from a previous run."
}

Write-Log "Creating container $ContainerName for version $Version..." -Level Info

# Get BC artifact URL
[string] $url = Get-BCArtifactUrl -version $Version -Country $Country
Write-Log "Retrieved artifact URL: $url" -Level Info

# Create container synchronously with NAV folder shared
New-BCContainerSync -ContainerName $ContainerName -Version $Version -ArtifactUrl $url -Credential $credential -AdditionalFolders @($RepoPath)

# Create compiler folder synchronously
New-BCCompilerFolderSync -ContainerName $ContainerName -ArtifactUrl $url

Initialize-ContainerForDevelopment -ContainerName $ContainerName -RepoVersion ([System.Version]$Version)

# Set output for GitHub Actions or return path
if ($env:GITHUB_OUTPUT) {
    "repo_path=$RepoPath" | Out-File -FilePath $env:GITHUB_OUTPUT -Append
}
