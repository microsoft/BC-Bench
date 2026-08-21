<#
.SYNOPSIS
    Sets up the BC container and clones the repository based on the provided dataset entry.
.DESCRIPTION
    This script is designed for categories that require a BC container environment or repository setup, should be skipped if not needed.
#>

using module .\DatasetEntry.psm1
using module .\BCBenchUtils.psm1
using module .\BCContainerManagement.psm1

param(
    [Parameter(Mandatory = $false)]
    [string]$Version,

    [Parameter(Mandatory = $false)]
    [string]$InstanceId,

    [Parameter(Mandatory = $true)]
    [string]$Category,

    [Parameter(Mandatory = $false)]
    [string]$DatasetPath = (Get-BCBenchDatasetPath -Category $Category),

    [Parameter(Mandatory = $false)]
    [string]$Country = "w1",

    [Parameter(Mandatory = $false)]
    [string]$ContainerName = $env:BC_CONTAINER_NAME ?? "bcbench",

    [Parameter(Mandatory = $false)]
    [string]$Username = $env:BC_SERVER_USERNAME ?? "admin",

    [Parameter(Mandatory = $false)]
    [SecureString]$Password,

    [Parameter(Mandatory = $false)]
    [string]$RepoPath,

    [Parameter(Mandatory = $false)]
    [switch]$SkipContainer,

    [Parameter(Mandatory = $false)]
    [switch]$SkipRepo
)

[DatasetEntry[]] $entries = Get-DatasetEntries -DatasetPath $DatasetPath -Version $Version -InstanceId $InstanceId
if ($InstanceId) {
    $Version = $entries[0].environment_setup_version
    Write-Log "Found version $Version for InstanceId $InstanceId" -Level Info
}
else {
    Write-Log "Found $($entries.Count) dataset entries to process." -Level Info
}

Write-Log "Setting up repository for version $Version, Dataset Path: $DatasetPath" -Level Info

if (-not $RepoPath) {
    $RepoPath = Join-Path -Path $env:GITHUB_WORKSPACE -ChildPath "testbed"
}
Write-Log "Using repository path: $RepoPath" -Level Info

if (Test-Path $RepoPath) {
    throw "Repository already exists at $RepoPath. This indicates the machine was not properly cleaned up from a previous run."
}

if (-not $SkipRepo) {
    [hashtable] $cloneInfo = Get-RepoCloneInfo -Entry $entries[0]
    [string] $commitSha = $entries[0].base_commit

    Write-Log "Cloning repository $($entries[0].repo) to $RepoPath" -Level Info
    Invoke-GitCloneWithRetry -RepoUrl $cloneInfo.Url -Token $cloneInfo.Token -ClonePath $RepoPath -CommitSha $commitSha -SparseCheckoutPaths $cloneInfo.SparseCheckoutPaths
}
else {
    # Categories that scaffold their own workspace still need the folder to exist: it is shared into
    # the container below, and Compile-AppInBcContainer throws for any path not shared with it.
    Write-Log "Skipping repository clone (SkipRepo flag set); creating empty workspace at $RepoPath" -Level Info
    New-Item -ItemType Directory -Path $RepoPath -Force | Out-Null
}

if (-not $SkipContainer) {
    [PSCredential]$credential = Get-BCCredential -Username $Username -Password $Password

    Import-Module BcContainerHelper -Force -DisableNameChecking

    Write-Log "Container name: $ContainerName" -Level Info

    if (Test-ContainerExists -containerName $ContainerName) {
        throw "Container $ContainerName already exists. This indicates the machine was not properly cleaned up from a previous run."
    }

    Write-Log "Creating container $ContainerName for version $Version..." -Level Info

    # TEMPORARY (remove before merge): Data Query tools only exist in BC 29, which is not GA on the
    # public feed yet, so pull the sandbox artifact from the insider feed.
    [string] $url = Get-BCArtifactUrl -version $Version -Country $Country -select Latest -storageAccount bcinsider -accept_insiderEula
    Write-Log "Retrieved artifact URL: $url" -Level Info

    # Create container synchronously with NAV folder shared
    New-BCContainerSync -ContainerName $ContainerName -Version $Version -ArtifactUrl $url -Credential $credential -AdditionalFolders @($RepoPath)

    # Create compiler folder synchronously
    New-BCCompilerFolderSync -ContainerName $ContainerName -ArtifactUrl $url

    Initialize-ContainerForDevelopment -ContainerName $ContainerName -RepoVersion ([System.Version]$Version)

    # data-query benchmarks the agent WITH the BC MCP server as a feedback loop. Publish the install
    # app that provisions and activates the 'BCBench' MCP configuration, then expose the endpoint and
    # company to the agent step so it can point its MCP client at the container.
    if ($Category -eq 'data-query') {
        Publish-MCPConfigApp -ContainerName $ContainerName -Version $Version -Credential $credential

        $mcpInfo = Get-BCMCPConnectionInfo -ContainerName $ContainerName
        Write-Log "BC MCP base URL: $($mcpInfo.BaseUrl) (company '$($mcpInfo.Company)')" -Level Info

        # TEMPORARY: probe the endpoint from the host before the agent runs (remove before merge).
        Write-BCMCPDiagnostics -BaseUrl $mcpInfo.BaseUrl -Company $mcpInfo.Company -Credential $credential

        if ($env:GITHUB_ENV) {
            "BC_MCP_URL=$($mcpInfo.BaseUrl)" | Out-File -FilePath $env:GITHUB_ENV -Append
            "BC_MCP_COMPANY=$($mcpInfo.Company)" | Out-File -FilePath $env:GITHUB_ENV -Append
        }
    }
}
else {
    Write-Log "Skipping BC container setup (SkipContainer flag set)" -Level Info
}

# Set output for GitHub Actions or return path
if ($env:GITHUB_OUTPUT) {
    "repo_path=$RepoPath" | Out-File -FilePath $env:GITHUB_OUTPUT -Append
}
