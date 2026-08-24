<#
.SYNOPSIS
    Capture BC Server (NST) diagnostics from a running BcContainerHelper container.

    Best-effort and non-fatal: pulls the container's Windows Application event log (NAV/MCP entries),
    the NST server configuration, and the persisted "MCP Configuration" row so we can see why the BC
    MCP endpoint exposes zero Data Query tools. Writes .log files into -OutputDir for artifact upload.
#>
param(
    [Parameter(Mandatory)][string]$ContainerName,
    [Parameter(Mandatory)][string]$OutputDir
)

$ErrorActionPreference = 'Continue'

function Write-Diag($message) { Write-Host "[Capture-NstLogs] $message" }

if (-not $ContainerName) {
    Write-Diag 'No container name provided; skipping NST log capture.'
    return
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# 1. NAV/MCP-related Application event log entries from inside the container.
try {
    Write-Diag "Capturing NST Application event log from '$ContainerName'..."
    $events = Invoke-ScriptInBcContainer -containerName $ContainerName -scriptblock {
        Get-WinEvent -LogName Application -MaxEvents 3000 -ErrorAction SilentlyContinue |
            Where-Object { $_.ProviderName -match 'NAV|Dynamics' -or $_.Message -match 'MCP|AlQuery|Data.?Query|query tool|tools/list' } |
            Sort-Object TimeCreated |
            ForEach-Object { '{0:o} [{1}] {2} (Id {3}): {4}' -f $_.TimeCreated, $_.LevelDisplayName, $_.ProviderName, $_.Id, ($_.Message -replace '\r?\n', ' ') }
    }
    ($events | Out-String) | Out-File -FilePath (Join-Path $OutputDir 'nst-eventlog.log') -Encoding utf8
    Write-Diag "Captured $(@($events).Count) NAV/MCP event(s)."
}
catch {
    "Event log capture failed: $_" | Out-File -FilePath (Join-Path $OutputDir 'nst-eventlog.log') -Encoding utf8
    Write-Diag "Event log capture failed: $_"
}

# 2. Discover any dedicated NAV/MCP event channels (in case MCP logs somewhere other than Application).
try {
    $channels = Invoke-ScriptInBcContainer -containerName $ContainerName -scriptblock {
        Get-WinEvent -ListLog * -ErrorAction SilentlyContinue |
            Where-Object { $_.LogName -match 'NAV|Dynamics|MCP' } |
            ForEach-Object { '{0} (records: {1})' -f $_.LogName, $_.RecordCount }
    }
    ($channels | Out-String) | Out-File -FilePath (Join-Path $OutputDir 'nst-eventchannels.log') -Encoding utf8
}
catch {
    Write-Diag "Event channel discovery failed: $_"
}

# 3. NST server configuration (feature keys / MCP-related settings).
try {
    Write-Diag 'Capturing NST server configuration...'
    $config = Get-BcContainerServerConfiguration -containerName $ContainerName
    ($config | Format-List * | Out-String) | Out-File -FilePath (Join-Path $OutputDir 'nst-serverconfig.log') -Encoding utf8
}
catch {
    Write-Diag "Server configuration capture failed: $_"
}

# 4. Persisted "MCP Configuration" row(s) - confirms whether EnableAlQueryTools actually got set.
try {
    Write-Diag 'Querying the MCP Configuration table...'
    $config = Get-BcContainerServerConfiguration -containerName $ContainerName
    $dbServer = $config.DatabaseServer
    $dbInstance = $config.DatabaseInstance
    $dbName = $config.DatabaseName
    $server = if ($dbInstance) { "$dbServer\$dbInstance" } else { $dbServer }

    $rows = Invoke-ScriptInBcContainer -containerName $ContainerName -scriptblock {
        param($sqlServer, $database)
        $table = (sqlcmd -S $sqlServer -d $database -h -1 -W -Q "SET NOCOUNT ON; SELECT TOP 1 name FROM sys.tables WHERE name LIKE '%MCP Configuration%'" 2>&1 | ForEach-Object { "$_".Trim() } | Where-Object { $_ -and $_ -notmatch 'rows affected' } | Select-Object -First 1)
        if ($table) {
            "Table: $table"
            '--- columns ---'
            sqlcmd -S $sqlServer -d $database -h -1 -Q "SET NOCOUNT ON; SELECT c.name FROM sys.columns c JOIN sys.tables t ON c.object_id = t.object_id WHERE t.name = '$table' ORDER BY c.column_id" 2>&1
            '--- row(s) (pipe-separated) ---'
            sqlcmd -S $sqlServer -d $database -s "|" -W -Q "SELECT * FROM [dbo].[$table]" 2>&1
        }
        else {
            'No table matching %MCP Configuration% found in the tenant database.'
        }
    } -argumentList $server, $dbName
    ($rows | Out-String) | Out-File -FilePath (Join-Path $OutputDir 'mcp-configuration.log') -Encoding utf8
}
catch {
    Write-Diag "MCP Configuration query failed: $_"
}

# 5. Install status of the MCP Config Setup app (published != installed; OnInstall must have run).
try {
    Write-Diag 'Checking MCP Config Setup app install status...'
    $apps = Get-BcContainerAppInfo -containerName $ContainerName -tenant default -tenantSpecificProperties |
        Where-Object { $_.Name -match 'MCP' }
    ($apps | Format-List Name, Publisher, Version, IsInstalled, IsPublished, SyncState | Out-String) | Out-File -FilePath (Join-Path $OutputDir 'mcp-app-status.log') -Encoding utf8
}
catch {
    Write-Diag "App install status check failed: $_"
}

Write-Diag 'NST diagnostics capture complete.'
