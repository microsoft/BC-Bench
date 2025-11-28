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

Import-Module BcContainerHelper -Force -DisableNameChecking

Write-Log "Container name: $ContainerName" -Level Info

[System.Management.Automation.Job]$containerJob = $null

if (Test-ContainerExists -containerName $ContainerName) {
    Write-Log "Container $ContainerName already exists, reusing it" -Level Warning
}
else {
    try {
        Write-Log "Creating container $ContainerName for version $Version..." -Level Info

        # Get BC artifact URL
        [string] $url = Get-BCArtifactUrl -version $Version -Country $Country
        Write-Log "Retrieved artifact URL: $url" -Level Info

        # Create container asynchronously with NAV folder shared
        $containerJob = New-BCContainerAsync -ContainerName $ContainerName -Version $Version -ArtifactUrl $url -Credential $credential -AdditionalFolders @($RepoPath)
    }
    catch {
        Write-Log "Failed to start container creation job for $ContainerName`: $($_.Exception.Message)" -Level Error
        exit 1
    }
}

if (Test-Path $RepoPath) {
    Write-Log "Repository already exists at $RepoPath, skipping clone." -Level Warning
}
else {
    try {
        [hashtable] $cloneInfo = Get-RepoCloneInfo -Entry $entries[0]
        [string] $commitSha = $entries[0].base_commit

        Write-Log "Cloning repository $($entries[0].repo) to $RepoPath" -Level Info
        Invoke-GitCloneWithRetry -RepoUrl $cloneInfo.Url -Token $cloneInfo.Token -ClonePath $RepoPath -CommitSha $commitSha
    }
    catch {
        Write-Log "Failed to clone repository ($($entries[0].repo)): $($_.Exception.Message)" -Level Error
        if ($containerJob) { Stop-Job $containerJob; Remove-Job $containerJob }
        exit 1
    }
}

if ($containerJob) {
    $success = Wait-JobWithProgress -Job $containerJob -StatusMessage "Container creation"
    if ($success) {
        Initialize-ContainerForDevelopment -ContainerName $ContainerName -RepoVersion ([System.Version]$Version)
    }
    else {
        exit 1
    }
}

# Set output for GitHub Actions or return path
if ($env:GITHUB_OUTPUT) {
    "repo_path=$RepoPath" | Out-File -FilePath $env:GITHUB_OUTPUT -Append
}
