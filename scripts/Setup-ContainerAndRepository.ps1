using module .\DatasetEntry.psm1
using module .\BCBenchUtils.psm1
using module .\BCContainerManagement.psm1

param(
    [Parameter(Mandatory=$false)]
    [string]$Version,

    [Parameter(Mandatory=$false)]
    [string]$InstanceId,

    [Parameter(Mandatory=$false)]
    [string]$DatasetPath = (Get-BCBenchDatasetPath),

    [Parameter(Mandatory=$false)]
    [string]$Country = "w1",

    [Parameter(Mandatory=$false)]
    [string]$Username='admin',

    [Parameter(Mandatory=$false)]
    [SecureString]$Password,

    [Parameter(Mandatory=$false)]
    [string]$RepoPath
)

[DatasetEntry[]] $entries = Get-DatasetEntries -DatasetPath $DatasetPath -Version $Version -InstanceId $InstanceId
if ($InstanceId) {
    $Version = $entries[0].environment_setup_version
    Write-Log "Found version $Version for InstanceId $InstanceId" -Level Info
} else {
    Write-Log "Found $($entries.Count) dataset entries to process." -Level Info
}

Write-Log "Setting up BC container and repository for version $Version, Dataset Path: $DatasetPath" -Level Info

[PSCredential]$credential = Get-BCCredential -Username $Username -Password $Password

if (-not $RepoPath) {
    $RepoPath = Join-Path -Path $env:TEMP -ChildPath "NAV-$Version"
    Write-Log "Using default NAV repository clone path: $RepoPath" -Level Info
} else {
    Write-Log "Using provided NAV repository clone path: $RepoPath" -Level Info
}

Import-Module BcContainerHelper -Force -DisableNameChecking

[string] $containerName = Get-StandardContainerName -Version $Version
Write-Log "Container name: $containerName" -Level Info

[System.Management.Automation.Job]$containerJob = $null

if (Test-ContainerExists -containerName $containerName) {
    Write-Log "Container $containerName already exists, reusing it" -Level Warning
} else {
    try {
        Write-Log "Creating container $containerName for version $Version..." -Level Info

        # Get BC artifact URL
        [string] $url = Get-BCArtifactUrl -version $Version -Country $Country
        Write-Log "Retrieved artifact URL: $url" -Level Info

        # Create container asynchronously with NAV folder shared
        $containerJob = New-BCContainerAsync -ContainerName $containerName -Version $Version -ArtifactUrl $url -Credential $credential -AdditionalFolders @($RepoPath)
    }
    catch {
        Write-Log "Failed to start container creation job for $containerName`: $($_.Exception.Message)" -Level Error
        exit 1
    }
}

if (Test-Path $RepoPath) {
    Write-Log "NAV repository already exists at $RepoPath, skipping clone." -Level Warning
} else {
    try {
        [string] $navBranch = "releases/$Version"
        [string] $navURL = 'https://dynamicssmb2.visualstudio.com/Dynamics%20SMB/_git/NAV'

        Invoke-GitCloneWithRetry -RepoUrl $navURL -Token $env:NAV_REPO_TOKEN -Branch $navBranch `
            -ClonePath $RepoPath -PrefetchCommits ($entries | Select-Object -ExpandProperty base_commit)
    }
    catch {
        Write-Log "Failed to clone NAV repository: $($_.Exception.Message)" -Level Error
        if ($containerJob) { Stop-Job $containerJob; Remove-Job $containerJob }
        exit 1
    }
}

if ($containerJob) {
    $success = Wait-JobWithProgress -Job $containerJob -StatusMessage "Container creation"
    if ($success) {
        Initialize-ContainerForDevelopment -ContainerName $ContainerName -RepoVersion ([System.Version]$Version)
    } else {
        exit 1
    }
}

# Set output for GitHub Actions or return path
if ($env:GITHUB_OUTPUT) {
    "nav_clone_path=$RepoPath" | Out-File -FilePath $env:GITHUB_OUTPUT -Append
    "container_name=$containerName" | Out-File -FilePath $env:GITHUB_OUTPUT -Append
}
