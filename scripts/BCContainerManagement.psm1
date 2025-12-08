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

    Write-Log "Container created successfully: $ContainerName" -Level Success
}

Export-ModuleMember -Function Test-Database, Set-AppVersion, Move-AppIntoDevScope, Initialize-ContainerForDevelopment, Test-ContainerExists, New-BCContainerSync
