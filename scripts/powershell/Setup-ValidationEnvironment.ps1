using module .\DatasetEntry.psm1
using module .\BCBenchUtils.psm1
using module .\BCContainerManagement.psm1

param(
    [Parameter(Mandatory=$true)]
    [string]$Version,

    [Parameter(Mandatory=$false)]
    [string]$DatasetPath = "$PSScriptRoot\..\..\dataset\bcbench_nav.jsonl",

    [Parameter(Mandatory=$false)]
    [string]$Country = "w1",

    [Parameter(Mandatory=$false)]
    [string]$Username='admin',

    [Parameter(Mandatory=$false)]
    [SecureString]$Password,

    [Parameter(Mandatory=$false)]
    [string]$NAVRepoPath
)

Write-Log "Setting up validation environment for version $Version, Dataset Path: $DatasetPath" -Level Info

[PSCredential]$credential = Get-BCCredential -Username $Username -Password $Password

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

# Determine NAV clone path first (before container creation)
if (-not $NAVRepoPath) {
    $NAVRepoPath = Join-Path -Path $env:TEMP -ChildPath "NAV-$Version"
    Write-Log "Using default NAV clone path: $NAVRepoPath" -Level Info
} else {
    Write-Log "Using provided NAV clone path: $NAVRepoPath" -Level Info
}

# Import required modules
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
        $containerJob = New-BCContainerAsync -ContainerName $containerName -Version $Version -ArtifactUrl $url -Credential $credential -AdditionalFolders @($NAVRepoPath)
    }
    catch {
        Write-Log "Failed to start container creation job for $containerName`: $($_.Exception.Message)" -Level Error
        exit 1
    }
}

if (Test-Path $NAVRepoPath) {
    Write-Log "NAV repository already exists at $NAVRepoPath, skipping clone." -Level Warning
} else {
    try {
        [string] $navBranch = "releases/$Version"
        [string] $navURL = 'https://dynamicssmb2.visualstudio.com/Dynamics%20SMB/_git/NAV'

        Invoke-GitCloneWithRetry -RepoUrl $navURL -Token $env:NAV_REPO_TOKEN -Branch $navBranch `
            -ClonePath $NAVRepoPath -PrefetchCommits ($versionEntries | Select-Object -ExpandProperty base_commit) `
            -SparseCheckoutPaths ($versionEntries | ForEach-Object { $_.project_paths } | Where-Object { $_ })
    }
    catch {
        Write-Log "Failed to clone NAV repository: $($_.Exception.Message)" -Level Error
        if ($containerJob) { Stop-Job $containerJob; Remove-Job $containerJob }
        exit 1
    }
}

# Wait for container creation job to complete (if it was started)
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
    "nav_clone_path=$NAVRepoPath" | Out-File -FilePath $env:GITHUB_OUTPUT -Append
}
