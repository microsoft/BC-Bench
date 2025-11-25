<#
.SYNOPSIS
    BC-Bench Utilities Module
.DESCRIPTION
    Common utility functions used across BC-Bench PowerShell scripts
#>

<#
.SYNOPSIS
    Creates a PSCredential object from various authentication sources
.DESCRIPTION
    Handles credential creation from parameter or environment variable with conflict detection
.PARAMETER Username
    The username for authentication
.PARAMETER Password
    Optional SecureString password parameter
.PARAMETER EnvironmentVariableName
    Name of environment variable containing password (default: BC_CONTAINER_PASSWORD)
.OUTPUTS
    PSCredential object
.EXAMPLE
    $cred = Get-BCCredential -Username "admin" -Password $securePassword
.EXAMPLE
    $cred = Get-BCCredential -Username "admin" # Uses BC_CONTAINER_PASSWORD env var
#>
function Get-BCCredential {
    [CmdletBinding()]
    [OutputType([PSCredential])]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Username,

        [Parameter(Mandatory = $false)]
        [SecureString]$Password,

        [Parameter(Mandatory = $false)]
        [string]$EnvironmentVariableName = "BC_CONTAINER_PASSWORD"
    )

    # Get environment password
    [string] $envPassword = [Environment]::GetEnvironmentVariable($EnvironmentVariableName)
    [bool] $hasParameterPassword = $null -ne $Password
    [bool] $hasEnvPassword = -not [string]::IsNullOrEmpty($envPassword)

    # Check for conflicts
    if ($hasParameterPassword -and $hasEnvPassword) {
        throw "Conflict: Both -Password parameter and $EnvironmentVariableName environment variable are provided. Please use only one method for providing the password."
    }

    # Create credential based on available source
    if ($hasParameterPassword) {
        Write-Verbose "Using Username/Password from parameters"
        return New-Object System.Management.Automation.PSCredential($Username, $Password)
    }
    elseif ($hasEnvPassword) {
        Write-Verbose "Using Username/Password from environment variable: $EnvironmentVariableName"
        $secureEnvPassword = ConvertTo-SecureString -String $envPassword -AsPlainText -Force
        return New-Object System.Management.Automation.PSCredential($Username, $secureEnvPassword)
    }
    else {
        throw "Authentication credentials are required. Provide either: 1. -Password parameter, 2. $EnvironmentVariableName environment variable"
    }
}

<#
.SYNOPSIS
    Clones a Git repository with authentication and retry logic
.DESCRIPTION
    Clones a repository using token authentication with configurable retry attempts
.PARAMETER RepoUrl
    Base URL of the repository (without authentication)
.PARAMETER Token
    Authentication token for repository access
.PARAMETER Branch
    Specific branch to clone
.PARAMETER ClonePath
    Local path where repository should be cloned
.PARAMETER MaxRetries
    Maximum number of retry attempts (default: 2)
.PARAMETER RetryDelaySeconds
    Delay between retry attempts in seconds (default: 5)
.PARAMETER CommitSha
    Optional specific commit SHA to checkout. If provided, performs a shallow clone of that commit.
.EXAMPLE
    Invoke-GitCloneWithRetry -RepoUrl "https://example.com/repo.git" -Token $token -Branch "main" -ClonePath "C:\temp\repo"
.EXAMPLE
    Invoke-GitCloneWithRetry -RepoUrl "https://example.com/repo.git" -Token $token -Branch "main" -ClonePath "C:\temp\repo" -CommitSha "abc123..."
#>
function Invoke-GitCloneWithRetry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoUrl,

        [Parameter(Mandatory = $true)]
        [string]$Token,

        [Parameter(Mandatory = $true)]
        [string]$Branch,

        [Parameter(Mandatory = $true)]
        [string]$ClonePath,

        [Parameter(Mandatory = $false)]
        [int]$MaxRetries = 3,

        [Parameter(Mandatory = $false)]
        [int]$RetryDelaySeconds = 5,

        [Parameter(Mandatory = $true)]
        [string]$CommitSha
    )

    # Remove existing clone if it exists
    if (Test-Path $ClonePath) {
        Write-Log "Removing existing directory at $ClonePath" -Level Warning
        Remove-Item -Path $ClonePath -Recurse -Force
    }

    # Extract domain and path from URL for authentication
    $uri = [System.Uri]$RepoUrl
    $authenticatedUrl = "https://$($Token)@$($uri.Authority)$($uri.PathAndQuery)"

    [int] $retryCount = 0
    [bool] $cloneSuccess = $false

    while ($retryCount -lt $MaxRetries -and -not $cloneSuccess) {
        $retryCount++
        try {
            Write-Log "Attempting repository clone (Attempt $retryCount/$MaxRetries)..." -Level Info

            Write-Log "Using shallow clone with specific commit: $CommitSha" -Level Debug
            # Initial shallow clone without checkout
            $cloneCommand = "git clone --depth 1 --filter=blob:none --no-checkout `"$authenticatedUrl`" `"$ClonePath`""
            $cloneResult = Invoke-Expression $cloneCommand 2>&1

            if ($LASTEXITCODE -ne 0) {
                throw "Git clone failed with exit code $LASTEXITCODE`: $cloneResult"
            }

            # Fetch the specific commit
            Write-Log "Fetching specific commit $CommitSha" -Level Debug
            $fetchResult = & git -C $ClonePath fetch --depth 1 origin $CommitSha 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to fetch commit $CommitSha`: $fetchResult"
            }

            # Checkout the specific commit
            Write-Log "Checking out commit $CommitSha" -Level Debug
            $checkoutResult = & git -C $ClonePath checkout $CommitSha 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to checkout commit $CommitSha`: $checkoutResult"
            }

            $cloneSuccess = $true
            Write-Log "Repository cloned and checked out to commit $CommitSha successfully" -Level Success
        }
        catch {
            Write-Log "Clone attempt $retryCount failed: $($_.Exception.Message)" -Level Error
            if ($retryCount -eq $MaxRetries) {
                Write-Log "Failed to clone repository after $MaxRetries attempts" -Level Error
                throw "Repository clone failed"
            }
            else {
                Write-Log "Retrying in $RetryDelaySeconds seconds..." -Level Warning
                Start-Sleep -Seconds $RetryDelaySeconds
            }
        }
    }
}

<#
.SYNOPSIS
    Monitors a PowerShell job until completion
.DESCRIPTION
    Monitors job progress with periodic status updates and handles completion/failure
.PARAMETER Job
    The PowerShell job to monitor
.PARAMETER PollingIntervalSeconds
    How often to check job status in seconds (default: 60)
.PARAMETER StatusMessage
    Custom status message to display during monitoring
.PARAMETER TimeoutMinutes
    Maximum time to wait for job completion in minutes (default: 20)
.OUTPUTS
    Returns $true if job completed successfully, $false otherwise
.EXAMPLE
    $job = Start-Job -ScriptBlock { Start-Sleep 30 }
    $success = Wait-JobWithProgress -Job $job -StatusMessage "Processing data"
.EXAMPLE
    $success = Wait-JobWithProgress -Job $job -StatusMessage "Long task" -TimeoutMinutes 30
#>
function Wait-JobWithProgress {
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory = $true)]
        [System.Management.Automation.Job]$Job,

        [Parameter(Mandatory = $false)]
        [int]$PollingIntervalSeconds = 60,

        [Parameter(Mandatory = $false)]
        [string]$StatusMessage = "Job",

        [Parameter(Mandatory = $false)]
        [int]$TimeoutMinutes = 40
    )

    Write-Log "Waiting for $StatusMessage to complete (timeout: $TimeoutMinutes minutes)..." -Level Info

    # Calculate timeout
    $timeoutSeconds = $TimeoutMinutes * 60
    $startTime = Get-Date
    $elapsedSeconds = 0

    # Monitor job progress
    do {
        Start-Sleep -Seconds $PollingIntervalSeconds
        $elapsedSeconds = ((Get-Date) - $startTime).TotalSeconds
        $remainingMinutes = [math]::Max(0, [math]::Round(($timeoutSeconds - $elapsedSeconds) / 60, 1))

        $jobState = Get-Job -Id $Job.Id | Select-Object -ExpandProperty State
        Write-Log "$StatusMessage status: $jobState (${remainingMinutes}min remaining)" -Level Info

        # Check for timeout
        if ($elapsedSeconds -ge $timeoutSeconds) {
            Write-Log "$StatusMessage timed out after $TimeoutMinutes minutes" -Level Warning
            Stop-Job $Job -ErrorAction SilentlyContinue
            Remove-Job $Job -Force -ErrorAction SilentlyContinue
            return $false
        }
    } while ($jobState -eq "Running")

    # Check job results
    if ($jobState -eq "Completed") {
        Write-Log "$StatusMessage completed successfully" -Level Success
        Remove-Job $Job
        return $true
    }
    else {
        # Get error details
        $jobError = Receive-Job $Job -ErrorAction SilentlyContinue
        $jobOutput = Receive-Job $Job
        Write-Log "$StatusMessage failed. State: $jobState" -Level Error
        if ($jobError) { Write-Log "Error details: $jobError" -Level Error }
        if ($jobOutput) { Write-Log "Output: $jobOutput" -Level Debug }
        Remove-Job $Job
        return $false
    }
}

<#
.SYNOPSIS
    Writes colorful log messages with standardized formatting
.DESCRIPTION
    Provides consistent logging output with color coding for different log levels.
    Optimized for GitHub Actions with proper formatting and colors.
.PARAMETER Message
    The message to log
.PARAMETER Level
    Log level: Info, Warning, Error, Success, Debug (default: Info)
.EXAMPLE
    Write-Log "Operation completed successfully" -Level Success
    Write-Log "Missing configuration file" -Level Warning
    Write-Log "Authentication failed" -Level Error
#>
function Write-Log {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Message,

        [Parameter(Mandatory = $false)]
        [ValidateSet("Info", "Warning", "Error", "Success", "Debug")]
        [string]$Level = "Info"
    )

    # Skip Debug messages unless RUNNER_DEBUG is enabled
    if ($Level -eq "Debug" -and $env:RUNNER_DEBUG -ne '1') {
        return
    }

    $logConfig = @{
        "Info"    = @{ Color = "White"; AnsiColor = "`e[37m" }      # White
        "Warning" = @{ Color = "Yellow"; AnsiColor = "`e[33m" }  # Yellow
        "Error"   = @{ Color = "Red"; AnsiColor = "`e[31m" }       # Red
        "Success" = @{ Color = "Green"; AnsiColor = "`e[32m" }   # Green
        "Debug"   = @{ Color = "Cyan"; AnsiColor = "`e[36m" }      # Cyan
    }

    $config = $logConfig[$Level]
    $timestamp = (Get-Date).ToString("HH:mm:ss")
    $formattedMessage = "[$timestamp] $Message"

    if ($env:CI -eq "true") {
        # Reset ANSI color code
        $resetColor = "`e[0m"

        # Using Console.Out preserves ANSI escape sequences in GitHub Actions logs
        [Console]::Out.WriteLine("$($config.AnsiColor)$formattedMessage$resetColor")

        # Emit GitHub Actions workflow commands for warnings and error
        if ($env:GITHUB_ACTIONS -eq "true" -and ($Level -eq "Warning" -or $Level -eq "Error")) {
            # Escape special characters for GitHub Actions
            # Per GitHub docs: need to escape %, \r, \n
            $escapedMessage = $Message -replace '%', '%25' -replace '\r', '%0D' -replace '\n', '%0A'

            # Determine the command type
            $command = if ($Level -eq "Error") { "error" } else { "warning" }

            # Output GitHub Actions annotation to stdout
            # Format: ::warning title={title}::{message}
            [Console]::Out.WriteLine("::$command title=BCBench::$escapedMessage")
        }
    }
    else {
        # Local execution - write with color
        Write-Host $formattedMessage -ForegroundColor $config.Color
    }
}

<#
.SYNOPSIS
    Applies a git patch from a string to the current repository
.DESCRIPTION
    Saves patch content to a temporary file and applies it using git apply.
    Cleans up the temporary file after application.
.PARAMETER PatchContent
    The patch content as a string
.PARAMETER PatchId
    Unique identifier for the patch
.PARAMETER RepositoryPath
    Optional path to the git repository (default: current directory)
.OUTPUTS
    Returns $true if patch applied successfully, $false otherwise
.EXAMPLE
    Invoke-GitApplyPatch -PatchContent $patchString -PatchId "test-123"
.EXAMPLE
    Invoke-GitApplyPatch -PatchContent $patchString -RepositoryPath "C:\repo"
#>
function Invoke-GitApplyPatch {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$PatchContent,

        [Parameter(Mandatory = $true)]
        [string]$PatchId,

        [Parameter(Mandatory = $false)]
        [string]$RepositoryPath
    )

    try {
        # Create temporary patch file
        [string]$patchPath = Join-Path -Path $env:TEMP -ChildPath "patch_$PatchId.diff"
        Write-Log "Saving patch to temporary file: $patchPath" -Level Debug
        $PatchContent | Out-File -FilePath $patchPath -Encoding utf8 -Force

        if ($RepositoryPath) {
            $applyResult = git -C $RepositoryPath apply --whitespace=nowarn $patchPath 2>&1
        }
        else {
            $applyResult = git apply --whitespace=nowarn $patchPath 2>&1
        }

        if ($LASTEXITCODE -ne 0) {
            throw "Failed to apply patch: $applyResult"
        }

        Write-Log "Patch applied successfully" -Level Success
    }
    catch {
        Write-Log "Exception while applying patch: $($_.Exception.Message)" -Level Error
        throw
    }
    finally {
        if (Test-Path $patchPath) {
            Remove-Item -Path $patchPath -Force -ErrorAction SilentlyContinue
        }
    }
}

<#
.SYNOPSIS
    Updates version numbers in a BC app project's app.json file
.DESCRIPTION
    Updates the application, platform, and dependency versions in an app.json file.
    Platform version uses only the first two digits (major.minor).
    Application and dependency versions use the full version with .0.0 appended.
    Automatically locates app.json in the project folder.
.PARAMETER ProjectPath
    Path to the BC app project folder containing app.json
.PARAMETER Version
    Target version string (e.g., "26.5" or "26.6")
.OUTPUTS
    Returns $true if update was successful, $false otherwise
.EXAMPLE
    Update-AppProjectVersion -ProjectPath "C:\repo\app" -Version "26.6"
    # Updates application to 26.6.0.0 and platform to 26.0.0.0
#>
function Update-AppProjectVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectPath,

        [Parameter(Mandatory = $true)]
        [string]$Version
    )
    Write-Log "Updating app project version in: $ProjectPath to version: $Version" -Level Info
    [string]$appJsonPath = Join-Path -Path $ProjectPath -ChildPath "app.json"

    if (-not (Test-Path $appJsonPath)) {
        throw "app.json not found at: $appJsonPath"
    }

    Write-Log "Reading app.json from: $appJsonPath" -Level Debug
    $appJson = Get-Content -Path $appJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json

    [string[]]$versionParts = $Version.Split('.')
    if ($versionParts.Count -lt 2) {
        throw "Invalid version format: $Version. Expected format: major.minor (e.g., 26.5)"
    }

    [string]$applicationVersion = "$($versionParts[0]).$($versionParts[1]).0.0"
    [string]$platformVersion = "$($versionParts[0]).0.0.0"

    Write-Log "Updating versions - Application: $applicationVersion, Platform: $platformVersion" -Level Debug

    $appJson.version = $applicationVersion

    if ($appJson.PSObject.Properties.Name -contains "application") {
        $appJson.application = $applicationVersion
    }
    else {
        Write-Log "'application' property does not exist in app.json under $ProjectPath" -Level Warning
    }

    $appJson.platform = $platformVersion

    if ($appJson.dependencies) {
        foreach ($dependency in $appJson.dependencies) {
            $dependency.version = $applicationVersion
        }
        Write-Log "Updated $($appJson.dependencies.Count) dependency version(s)" -Level Debug
    }

    $appJson | ConvertTo-Json -Depth 10 | Set-Content -Path $appJsonPath -Encoding UTF8 -Force

    Write-Log "Successfully updated app.json at: $appJsonPath" -Level Success
}

function Get-BCBenchDatasetPath {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory = $false)]
        [string]$DatasetName = "bcbench_nav.jsonl"
    )

    [string] $projectRoot = Split-Path $PSScriptRoot -Parent
    return Join-Path $projectRoot "dataset" $DatasetName
}

Export-ModuleMember -Function Get-BCCredential, Invoke-GitCloneWithRetry, Wait-JobWithProgress, Get-EnvironmentVariable, Write-Log, Invoke-GitApplyPatch, Update-AppProjectVersion, Get-BCBenchDatasetPath
