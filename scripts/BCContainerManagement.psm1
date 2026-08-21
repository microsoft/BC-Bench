<#
.SYNOPSIS
    BC Container Management Module
.DESCRIPTION
    Provides functions for managing Business Central containers, including creation, initialization, and SQL operations
#>

<#
    .SYNOPSIS
    Run a SQL command on the specified server
    .DESCRIPTION
    This function runs a SQL command on the specified server
    .PARAMETER Server
    The hostname of the SQL server
    .PARAMETER Command
    The SQL command to run
    .PARAMETER CommandTimeout
    The timeout for the command
#>
function Invoke-SqlCommand() {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Server,
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $false)]
        [int] $CommandTimeout = 0
    )

    $Options = @{}
    if ($CommandTimeout) {
        $Options["QueryTimeout"] = $CommandTimeout
    }

    Write-Verbose "Executing SQL query ($Server): ""$Command"""
    Invoke-Sqlcmd -Query $Command @Options
}

<#
    .SYNOPSIS
    Checks existance of database
    .DESCRIPTION
    Checks if the specified database exists on the SQL server
    .PARAMETER DatabaseName
    The name of the database to check
    .PARAMETER DatabaseServer
    The hostname of the SQL server
    .OUTPUTS
    Returns true if database exists otherwise false
#>
function Test-Database() {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DatabaseName,
        [Parameter(Mandatory = $false)]
        [string]$DatabaseServer = '.'
    )

    $sqlCommandText = @"
        USE MASTER
        SELECT '1' FROM SYS.DATABASES WHERE NAME = '$DatabaseName'
        GO
"@

    return ($null -ne (Invoke-SqlCommand -Server $DatabaseServer -Command $sqlCommandText))
}

<#
    .SYNOPSIS
    Set the version of an app in the specified database
    .DESCRIPTION
    This function sets the version of an app in the specified database
    .PARAMETER Name
    The name of the app
    .PARAMETER DatabaseName
    The name of the database
    .PARAMETER Major
    The major version number
    .PARAMETER Minor
    The minor version number
    .PARAMETER Publisher
    The publisher of the app
    .PARAMETER DatabaseServer
    The hostname of the SQL server
#>
function Set-AppVersion() {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$DatabaseName,
        [Parameter(Mandatory = $true)]
        [string]$Major,
        [Parameter(Mandatory = $true)]
        [string]$Minor,
        [Parameter(Mandatory = $false)]
        [string]$Publisher = 'Microsoft',
        [Parameter(Mandatory = $false)]
        [string]$DatabaseServer = '.'
    )

    $command = @"
    UPDATE [$DatabaseName].[dbo].[Published Application]
    SET [Version Major] = $Major, [Version Minor] = $Minor, [Version Build] = 0, [Version Revision] = 0
    WHERE Name = '$Name' and Publisher = '$Publisher';

    UPDATE [$DatabaseName].[dbo].[Application Dependency]
    SET [Dependency Version Major] = $Major, [Dependency Version Minor] = $Minor, [Dependency Version Build] = 0, [Dependency Version Revision] = 0
    WHERE [Dependency Name] = '$Name' and [Dependency Publisher] = '$Publisher';

    UPDATE [$DatabaseName].[dbo].[NAV App Installed App]
    SET [Version Major] = $Major, [Version Minor] = $Minor, [Version Build] = 0, [Version Revision] = 0
    WHERE Name = '$Name' and Publisher = '$Publisher';

    UPDATE [$DatabaseName].[dbo].[`$ndo`$navappschematracking]
    SET [version] = '$Major.$Minor.0.0', [baselineversion] = '$Major.$Minor.0.0'
    WHERE [name] = '$Name' and [publisher] = '$Publisher';
"@

    Invoke-SqlCommand -Command $command -Server $DatabaseServer
}

<#
    .SYNOPSIS
    Move the app identified by the given name and publisher from the global scope to the tenant scope

    .PARAMETER Name
    The app's name, as defined in the app's manifest.

    .PARAMETER DatabaseName
    The database on which to execute the query.

    .PARAMETER Publisher
    The app's publisher, as defined in the app's manifest.

    .PARAMETER TenantId
    The tenant in whose scope the app should be moved.

    .PARAMETER DatabaseServer
    The database server on which to run the query.
#>
function Move-AppIntoDevScope() {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$DatabaseName,
        [Parameter(Mandatory = $false)]
        [string]$Publisher = 'Microsoft',
        [Parameter(Mandatory = $false)]
        [string]$TenantId = 'default',
        [Parameter(Mandatory = $false)]
        [string]$DatabaseServer = '.'
    )
    if (!$TenantId) {
        $TenantId = 'default'
    }

    $command = @"
    UPDATE [$DatabaseName].[dbo].[Published Application]
    SET [Published As] = 2, [Tenant ID] = '$TenantId'
"@
    Invoke-SqlCommand -Command $command -Server $DatabaseServer
}

<#
    .SYNOPSIS
    Initialize the container for development
    .DESCRIPTION
    This function moves all installed apps to the dev scope and sets the version of the apps to the version of the repo.
    .PARAMETER ContainerName
    The name of the container to initialize
    .PARAMETER RepoVersion
    The version of the repo
    .EXAMPLE
    Initialize-ContainerForDevelopment -ContainerName "BC-20210101" -RepoVersion 25.0
#>
function Initialize-ContainerForDevelopment() {
    param(
        [string] $ContainerName,
        [System.Version] $RepoVersion
    )

    $BCContainerModule = "$PSScriptRoot\BCContainerManagement.psm1"
    $containerModulePath = "C:\Run\bcbench\BCContainerManagement.psm1"
    Copy-FileToBcContainer -containerName $ContainerName -localpath $BCContainerModule -containerPath $containerModulePath

    Invoke-ScriptInBcContainer -containerName $ContainerName -scriptblock {
        param([string] $ContainerModule, [System.Version] $RepoVersion, [string] $DatabaseName = "CRONUS")

        Import-Module $ContainerModule -DisableNameChecking -Force

        $server = Get-NAVServerInstance
        Write-Host "Server: $($server.ServerInstance)" -ForegroundColor Green

        if (-not(Test-Database -DatabaseName $DatabaseName)) {
            throw "Database $DatabaseName does not exist"
        }

        $installedApps = @(Get-NAVAppInfo -ServerInstance $server.ServerInstance)

        # Check that all apps are moved to the dev scope and that the version is reset to the repo version
        # If they are, we can skip the rest of the script
        if (-not ($installedApps | Where-Object { $_.Scope -eq 'Global' })) {
            Write-Host "All apps are already in the Dev Scope" -ForegroundColor Yellow
            if (-not ($installedApps | Where-Object { $_.Version -notmatch "\d+\.\d+\.0\.0" })) {
                Write-Host "All apps are already at version $($RepoVersion).0.0" -ForegroundColor Yellow
                return
            }
        }

        Stop-NAVServerInstance -ServerInstance $server.ServerInstance

        Write-Host "Moving $($installedApps.Count) apps to Dev Scope and setting version to $($RepoVersion).0.0"
        try {
            $installedApps | ForEach-Object {
                if ($_.Scope -eq 'Global') {
                    Move-AppIntoDevScope -Name ($_.Name) -DatabaseName $DatabaseName
                }
                if ($_.Version -ne "$($RepoVersion.Major).$($RepoVersion.Minor).0.0") {
                    Set-AppVersion -Name ($_.Name) -DatabaseName $DatabaseName -Major $RepoVersion.Major -Minor $RepoVersion.Minor
                }
            }
        }
        finally {
            Write-Host "Starting server instance $($server.ServerInstance)" -ForegroundColor Green
            Start-NAVServerInstance -ServerInstance $server.ServerInstance
        }

    } -argumentList $containerModulePath, $RepoVersion
}

<#
    .Synopsis
    Checks if a container with the specified name exists.
    .PARAMETER ContainerName
    The name of the container to check
    .OUTPUTS
    Returns true if container exists, false otherwise
#>
function Test-ContainerExists {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ContainerName
    )
    return ($null -ne $(docker ps -q -f name="$ContainerName"))
}

<#
    .SYNOPSIS
    Creates a new BC container with the specified parameters
    .DESCRIPTION
    Creates a Business Central container using BcContainerHelper with proper error handling
    .PARAMETER ContainerName
    Name for the new container
    .PARAMETER ArtifactUrl
    BC artifact URL for the container
    .PARAMETER Credential
    Credentials for container authentication
    .PARAMETER AcceptEula
    Whether to accept EULA (default: true)
    .PARAMETER AuthType
    Authentication type (default: UserPassword)
    .EXAMPLE
    New-BCContainerSync -ContainerName "test-container" -ArtifactUrl $url -Credential $cred
#>
function New-BCContainerSync {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName,

        [Parameter(Mandatory = $true)]
        [string]$Version,

        [Parameter(Mandatory = $true)]
        [string]$ArtifactUrl,

        [Parameter(Mandatory = $true)]
        [PSCredential]$Credential,

        [Parameter(Mandatory = $false)]
        [bool]$AcceptEula = $true,

        [Parameter(Mandatory = $false)]
        [string]$AuthType = "UserPassword",

        [Parameter(Mandatory = $false)]
        [string[]]$AdditionalFolders = @()
    )

    Write-Log "Creating container: $ContainerName" -Level Info

    $params = @{
        artifactUrl              = $ArtifactUrl
        containerName            = $ContainerName
        auth                     = $AuthType
        credential               = $Credential
        includeTestToolkit       = $true
        includeTestLibrariesOnly = $true
        multitenant              = $false
        shortcuts                = 'None'
        memoryLimit              = "16G"
        isolation                = "hyperv"
        # TEMPORARY (remove before merge): required to build a container from an insider (BC 29) artifact.
        accept_insiderEula       = $true
    }

    if ($AcceptEula) {
        $params.accept_eula = $true
    }

    if ($AdditionalFolders -and $AdditionalFolders.Count -gt 0) {
        [string[]]$volumeMappings = @()
        foreach ($folder in $AdditionalFolders) {
            $volumeMappings += "--volume"
            $volumeMappings += "${folder}:C:\Source"
        }
        $params.additionalParameters = $volumeMappings
    }

    New-BCContainer @params

    # Workaround: BC v24 artifacts predate manifest.json, so BcContainerHelper cannot determine the required .NET major
    # and falls back to "C:\Program Files\dotnet\shared", which causes AL0196 ambiguous TimeSpan.FromSeconds errors on runner images shipping .NET 10.
    # Inject a synthetic manifest so Compile-AppInBcContainer pins probing to .NET 8.
    # Drop this once navcontainerhelper#4136 (or equivalent platform-version fallback) ships.
    if ($Version.StartsWith("24")) {
        $manifestPath = "C:\ProgramData\BcContainerHelper\Extensions\$ContainerName\manifest.json"
        Write-Log "Injecting synthetic manifest.json (dotNetVersion=8.0.0) at $manifestPath for v24 compatibility" -Level Info
        '{"dotNetVersion":"8.0.0"}' | Set-Content -Path $manifestPath -Encoding UTF8 -Force
    }

    Write-Log "Container created successfully: $ContainerName" -Level Success
}

function New-BCCompilerFolderSync {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName,

        [Parameter(Mandatory = $true)]
        [string]$ArtifactUrl
    )

    Write-Log "Creating compiler folder for container: $ContainerName" -Level Info

    [string]$compilerFolder = New-BcCompilerFolder -artifactUrl $ArtifactUrl -containerName $ContainerName

    Write-Log "Compiler folder created at: $compilerFolder" -Level Success
}

function Publish-MCPConfigApp {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName,

        [Parameter(Mandatory = $true)]
        [string]$Version,

        [Parameter(Mandatory = $true)]
        [PSCredential]$Credential,

        [Parameter(Mandatory = $true)]
        [string]$BuildRoot
    )

    Import-Module "$PSScriptRoot\AppUtils.psm1" -Force -DisableNameChecking

    [int]$major = ([System.Version]$Version).Major
    [string]$sourceFolder = Join-Path $PSScriptRoot "al\mcp-config-setup"
    # Build inside BuildRoot: Compile-AppInBcContainer only accepts a project folder that is shared with
    # the container, and BuildRoot ($RepoPath) is the folder mounted into it. Cleaned up after publish so
    # nothing leaks into the agent's workspace.
    [string]$buildFolder = Join-Path $BuildRoot ".bcbench-mcp-config-app"

    if (Test-Path $buildFolder) {
        Remove-Item -Path $buildFolder -Recurse -Force
    }
    Copy-Item -Path $sourceFolder -Destination $buildFolder -Recurse -Force

    # The source keeps a placeholder so the same app builds against any evaluated BC version;
    # pin the app/platform dependency to the container's major version at publish time.
    [string]$appJsonPath = Join-Path $buildFolder "app.json"
    (Get-Content -Path $appJsonPath -Raw).Replace("__APP_VERSION__", "$major.0.0.0") | Set-Content -Path $appJsonPath -Encoding UTF8

    try {
        Write-Log "Publishing BC-Bench MCP config app to provision the MCP configuration..." -Level Info
        Invoke-AppBuildAndPublish -containerName $ContainerName -appProjectFolder $buildFolder -credential $Credential -skipVerification -useDevEndpoint
        Write-Log "BC MCP configuration 'BCBench' provisioned and activated." -Level Success
    }
    finally {
        Remove-Item -Path $buildFolder -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Get-BCMCPConnectionInfo {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName
    )

    # The evaluated agent runs on the host, not inside the container, and the runner does not update
    # its hosts file -- so reach the BC web listener by the container's IP address.
    [string]$ip = Get-BcContainerIpAddress -containerName $ContainerName
    if (-not $ip) {
        throw "Could not resolve IP address for container $ContainerName; BC MCP endpoint is unreachable from the host."
    }

    # BcContainerHelper containers always serve the 'BC' instance on port 7048; the MCP endpoint hangs
    # off the same base as the API endpoint the query harness already uses (base + '/mcp').
    [string]$baseUrl = "http://${ip}:7048/BC"

    $companies = @(Get-CompanyInBcContainer -containerName $ContainerName)
    $evaluationCompany = $companies | Where-Object { $_.EvaluationCompany } | Select-Object -First 1
    if (-not $evaluationCompany) {
        $evaluationCompany = $companies | Select-Object -First 1
    }

    # BcContainerHelper has exposed the company name as either CompanyName or Name across versions.
    [string]$company = $evaluationCompany.CompanyName
    if (-not $company) {
        $company = $evaluationCompany.Name
    }

    return [PSCustomObject]@{
        BaseUrl = $baseUrl
        Company = $company
    }
}

function Write-BCMCPDiagnostics {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$BaseUrl,

        [Parameter(Mandatory = $false)]
        [string]$Company,

        [Parameter(Mandatory = $true)]
        [PSCredential]$Credential,

        [Parameter(Mandatory = $false)]
        [string]$ConfigurationName = 'BCBench'
    )

    # TEMPORARY diagnostics (remove before merge): probe the BC MCP endpoint from the HOST exactly as
    # the evaluated agent will, so runner-only failures (reachability / auth / MCP config / tools) show
    # up in the setup log instead of being guessed from the agent's discarded logs. Never throws.
    $pair = "$($Credential.UserName):$($Credential.GetNetworkCredential().Password)"
    $basic = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))

    Write-Log "===== BC MCP DIAGNOSTICS =====" -Level Info
    Write-Log "BaseUrl=$BaseUrl  Company='$Company'  ConfigurationName=$ConfigurationName" -Level Info

    # 1) API listener reachability + Basic auth sanity against a known-good endpoint.
    try {
        $companiesUri = "$BaseUrl/api/v2.0/companies"
        $resp = Invoke-WebRequest -Uri $companiesUri -Headers @{ Authorization = $basic } -SkipHttpErrorCheck -UseBasicParsing -TimeoutSec 60
        Write-Log "[probe:companies] GET $companiesUri -> HTTP $($resp.StatusCode)" -Level Info
        Write-Log "[probe:companies] body: $($resp.Content.Substring(0, [Math]::Min(600, $resp.Content.Length)))" -Level Info
    }
    catch {
        Write-Log "[probe:companies] EXCEPTION: $($_.Exception.Message)" -Level Warning
    }

    # 2) MCP endpoint: initialize, then tools/list if a session is granted.
    $mcpUri = "$BaseUrl/mcp"
    $headers = @{
        Authorization     = $basic
        ConfigurationName = $ConfigurationName
        Accept            = 'application/json, text/event-stream'
    }
    if ($Company) { $headers['Company'] = $Company }

    $initBody = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"bcbench-diag","version":"1.0"}}}'
    try {
        $resp = Invoke-WebRequest -Uri $mcpUri -Method Post -Headers $headers -Body $initBody -ContentType 'application/json' -SkipHttpErrorCheck -UseBasicParsing -TimeoutSec 60
        Write-Log "[probe:mcp-initialize] POST $mcpUri -> HTTP $($resp.StatusCode)" -Level Info

        $sessionId = $resp.Headers['Mcp-Session-Id']
        if ($sessionId -is [array]) { $sessionId = $sessionId[0] }
        Write-Log "[probe:mcp-initialize] Mcp-Session-Id=$sessionId" -Level Info
        Write-Log "[probe:mcp-initialize] body: $($resp.Content.Substring(0, [Math]::Min(1200, $resp.Content.Length)))" -Level Info

        if ($sessionId) {
            $sessionHeaders = $headers.Clone()
            $sessionHeaders['Mcp-Session-Id'] = $sessionId
            Invoke-WebRequest -Uri $mcpUri -Method Post -Headers $sessionHeaders -Body '{"jsonrpc":"2.0","method":"notifications/initialized"}' -ContentType 'application/json' -SkipHttpErrorCheck -UseBasicParsing -TimeoutSec 60 | Out-Null
            $toolsResp = Invoke-WebRequest -Uri $mcpUri -Method Post -Headers $sessionHeaders -Body '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' -ContentType 'application/json' -SkipHttpErrorCheck -UseBasicParsing -TimeoutSec 60
            Write-Log "[probe:mcp-tools] tools/list -> HTTP $($toolsResp.StatusCode)" -Level Info
            Write-Log "[probe:mcp-tools] body: $($toolsResp.Content.Substring(0, [Math]::Min(2000, $toolsResp.Content.Length)))" -Level Info
        }
    }
    catch {
        Write-Log "[probe:mcp] EXCEPTION: $($_.Exception.Message)" -Level Warning
    }

    Write-Log "===== END BC MCP DIAGNOSTICS =====" -Level Info
}

Export-ModuleMember -Function Test-Database, Set-AppVersion, Move-AppIntoDevScope, Initialize-ContainerForDevelopment, Test-ContainerExists, New-BCContainerSync, New-BCCompilerFolderSync, Publish-MCPConfigApp, Get-BCMCPConnectionInfo, Write-BCMCPDiagnostics
