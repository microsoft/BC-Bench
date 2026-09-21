Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "BugFixLifecycle.psm1") -Force -DisableNameChecking

function Invoke-BCBenchRehearsalProbe {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ContainerName,
        [Parameter(Mandatory)][string]$ExpectedContainerId,
        [Parameter(Mandatory)][string]$ExpectedInvocationId,
        [Parameter(Mandatory)][string]$DatabaseName,
        [Parameter(Mandatory)][string]$DatabaseFolder,
        [Parameter(Mandatory)][ValidatePattern('^BCBenchRehearsal_[a-f0-9]{32}$')][string]$ProbeName,
        [Parameter(Mandatory)][ValidateSet("Read", "Create", "Mutate")][string]$Mode,
        [Parameter(DontShow)][hashtable]$Operations = @{}
    )

    if ($ExpectedContainerId -cnotmatch '^[a-zA-Z0-9-]{1,128}$' -or $ExpectedInvocationId -cnotmatch '^[a-zA-Z0-9-]{1,128}$') {
        throw "Invalid SQL probe ownership identifiers."
    }
    $context = Assert-BCBenchContainerOwnership -ContainerName $ContainerName -ExpectedContainerId $ExpectedContainerId `
        -ExpectedInvocationId $ExpectedInvocationId -Operations $Operations
    $topology = Get-BCBenchDatabaseTopology -ContainerName $ContainerName -ExpectedContainerId $ExpectedContainerId `
        -ExpectedInvocationId $ExpectedInvocationId -Operations $Operations
    if (-not $topology.database_online -or $topology.database_name -cne $DatabaseName -or $topology.database_folder -cne $DatabaseFolder) {
        throw "SQL probe topology differs from the owned checkpoint."
    }
    $owner = "${ExpectedInvocationId}:${ExpectedContainerId}"
    $sql = @"
SET NOCOUNT ON;
SET XACT_ABORT ON;
DECLARE @objectId int = OBJECT_ID(N'dbo.$ProbeName');
IF @objectId IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM sys.extended_properties
    WHERE class = 1 AND major_id = @objectId AND minor_id = 0
      AND name = N'BCBenchOwner' AND CONVERT(nvarchar(300), value) = N'$owner'
)
    THROW 51000, 'SQL probe ownership marker mismatch.', 1;
"@
    if ($Mode -eq "Create") {
        $sql += @"

IF @objectId IS NOT NULL THROW 51000, 'Refusing an existing SQL probe object.', 1;
BEGIN TRANSACTION;
CREATE TABLE [dbo].[$ProbeName] (MarkerId int NOT NULL PRIMARY KEY, ProbeValue int NOT NULL);
EXEC sys.sp_addextendedproperty @name=N'BCBenchOwner', @value=N'$owner',
    @level0type=N'SCHEMA', @level0name=N'dbo', @level1type=N'TABLE', @level1name=N'$ProbeName';
INSERT INTO [dbo].[$ProbeName] (MarkerId, ProbeValue) VALUES (1, 17);
COMMIT;
"@
    }
    elseif ($Mode -eq "Mutate") {
        $sql += @"

IF @objectId IS NULL THROW 51000, 'Owned SQL probe is missing.', 1;
IF (SELECT COUNT(*) FROM [dbo].[$ProbeName]) <> 1
    OR NOT EXISTS (SELECT 1 FROM [dbo].[$ProbeName] WHERE MarkerId=1 AND ProbeValue=17)
    THROW 51000, 'SQL probe initial row mismatch.', 1;
BEGIN TRANSACTION;
UPDATE [dbo].[$ProbeName] SET ProbeValue=29 WHERE MarkerId=1 AND ProbeValue=17;
ALTER TABLE [dbo].[$ProbeName] ADD MutatedColumn int NULL;
COMMIT;
"@
    }
    else {
        $sql += @"

SELECT 'database_files' AS kind,
    CONCAT(DB_NAME(), ':', file_id, ':', type_desc, ':', physical_name, ':', state_desc) AS value
FROM sys.database_files ORDER BY file_id;
IF @objectId IS NOT NULL BEGIN
    SELECT 'columns' AS kind, CONCAT(column_id, ':', name, ':', TYPE_NAME(user_type_id), ':', max_length, ':', is_nullable) AS value
    FROM sys.columns WHERE object_id=@objectId ORDER BY column_id;
    SELECT 'rows' AS kind, CONCAT(MarkerId, ':', ProbeValue) AS value FROM [dbo].[$ProbeName] ORDER BY MarkerId;
END;
"@
    }
    $context | Add-Member -NotePropertyName Sql -NotePropertyValue $sql
    $context | Add-Member -NotePropertyName DatabaseName -NotePropertyValue $DatabaseName
    return Invoke-BCBenchOperation -Operations $Operations -Name ExecuteProbe -Context $context -Default {
        param($c)
        Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
        Assert-BCBenchContainerOwnership -ContainerName $c.ContainerName -ExpectedContainerId $c.ContainerId `
            -ExpectedInvocationId $c.ContainerInvocationId -Operations @{} | Out-Null
        Invoke-ScriptInBcContainer -containerName $c.ContainerId -ScriptBlock {
            param([string]$Sql, [string]$ExpectedDatabase)
            $instances = @(Get-NAVServerInstance)
            if ($instances.Count -ne 1) { throw "Rehearsal requires exactly one BC server instance." }
            $configuration = Get-NAVServerConfiguration -ServerInstance $instances[0].ServerInstance
            $name = [string]($configuration | Where-Object KeyName -eq "DatabaseName").KeyValue
            $server = [string]($configuration | Where-Object KeyName -eq "DatabaseServer").KeyValue
            $instance = [string]($configuration | Where-Object KeyName -eq "DatabaseInstance").KeyValue
            $multitenant = [string]($configuration | Where-Object KeyName -eq "Multitenant").KeyValue
            if ($name -cne $ExpectedDatabase -or $server -notin @(".", "localhost", $env:COMPUTERNAME) -or $multitenant -eq "true") {
                throw "Rehearsal only supports the exact local single-tenant checkpoint database."
            }
            $builder = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
            $builder.DataSource = if ($instance) { "$server\$instance" } else { $server }
            $builder.InitialCatalog = $name
            $builder.IntegratedSecurity = $true
            $builder.ConnectTimeout = 15
            $connection = New-Object System.Data.SqlClient.SqlConnection($builder.ConnectionString)
            try {
                $connection.Open()
                $command = $connection.CreateCommand()
                $command.CommandTimeout = 60
                $command.CommandText = $Sql
                $reader = $command.ExecuteReader()
                try {
                    $result = @{ database_files = @(); columns = @(); rows = @() }
                    do {
                        while ($reader.Read()) {
                            $kind = [string]$reader["kind"]
                            if (-not $result.ContainsKey($kind)) { throw "Unexpected SQL probe result." }
                            $result[$kind] += [string]$reader["value"]
                        }
                    } while ($reader.NextResult())
                    [PSCustomObject]$result
                }
                finally { $reader.Dispose(); $command.Dispose() }
            }
            finally { $connection.Dispose() }
        } -ArgumentList $c.Sql, $c.DatabaseName
    }
}

function Get-BCBenchRehearsalDiscovery {
    param(
        [Parameter(Mandatory)][string]$ContainerName,
        [Parameter(Mandatory)][string]$ExpectedContainerId,
        [Parameter(Mandatory)][string]$ExpectedInvocationId,
        [Parameter(Mandatory)][PSCredential]$Credential,
        [Parameter(Mandatory)][string]$Company,
        [Parameter(DontShow)][hashtable]$Operations = @{}
    )
    $context = Assert-BCBenchContainerOwnership -ContainerName $ContainerName -ExpectedContainerId $ExpectedContainerId `
        -ExpectedInvocationId $ExpectedInvocationId -Operations $Operations
    $context | Add-Member -NotePropertyName Credential -NotePropertyValue $Credential
    $context | Add-Member -NotePropertyName Company -NotePropertyValue $Company
    $tests = @(Invoke-BCBenchOperation -Operations $Operations -Name DiscoverTests -Context $context -Default {
        param($c)
        Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
        Get-TestsFromBcContainer -containerName $c.ContainerId -credential $c.Credential -companyName $c.Company -ignoreGroups
    })
    [string[]]$identities = @(
        foreach ($codeunit in $tests) {
            if ([int]$codeunit.Id -le 0) { throw "Invalid discovery codeunit ID." }
            foreach ($method in @($codeunit.Tests)) {
                if ([string]::IsNullOrWhiteSpace([string]$method)) { throw "Invalid discovery method." }
                "$([int]$codeunit.Id):$method"
            }
        }
    )
    return $identities
}

function Uninstall-BCBenchRehearsalTestApp {
    param(
        [Parameter(Mandatory)][string]$ContainerName,
        [Parameter(Mandatory)][string]$ExpectedContainerId,
        [Parameter(Mandatory)][string]$ExpectedInvocationId,
        [Parameter(Mandatory)][PSObject]$App,
        [Parameter(DontShow)][hashtable]$Operations = @{}
    )
    $context = Assert-BCBenchContainerOwnership -ContainerName $ContainerName -ExpectedContainerId $ExpectedContainerId `
        -ExpectedInvocationId $ExpectedInvocationId -Operations $Operations
    $apps = @(Get-BCBenchAppInventory -ContainerName $ContainerName -ExpectedContainerId $ExpectedContainerId `
        -ExpectedInvocationId $ExpectedInvocationId -Operations $Operations)
    $matches = @($apps | Where-Object { $_.app_id -ceq $App.app_id })
    if ($matches.Count -ne 1 -or -not (Test-BCBenchAppInventoryEqual -Actual $matches -Expected @($App)) -or -not $App.installed) {
        throw "Entry-owned test app identity changed before uninstall."
    }
    $context | Add-Member -NotePropertyName App -NotePropertyValue $App
    Invoke-BCBenchOperation -Operations $Operations -Name UninstallTestApp -Context $context -Default {
        param($c)
        Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
        Assert-BCBenchContainerOwnership -ContainerName $c.ContainerName -ExpectedContainerId $c.ContainerId `
            -ExpectedInvocationId $c.ContainerInvocationId -Operations @{} | Out-Null
        Invoke-ScriptInBcContainer -containerName $c.ContainerId -ScriptBlock {
            param($App)
            $instances = @(Get-NAVServerInstance)
            if ($instances.Count -ne 1) { throw "Rehearsal requires exactly one BC server instance." }
            $instance = $instances[0].ServerInstance
            $matches = @(Get-NAVAppInfo -ServerInstance $instance -Tenant default | Where-Object {
                [string]$_.AppId -eq [string]$App.app_id -and [string]$_.Version -eq [string]$App.version
            })
            if ($matches.Count -ne 1 -or [string]$matches[0].Name -cne [string]$App.name -or [string]$matches[0].Publisher -cne [string]$App.publisher) {
                throw "Exact entry test app not found in tenant."
            }
            # No Force, cascade, unpublish, data deletion, or package-cleanup fallback.
            Uninstall-NAVApp -ServerInstance $instance -Tenant default -Name $App.name `
                -Publisher $App.publisher -Version $App.version -Confirm:$false
        } -ArgumentList $c.App
    } | Out-Null
}

function Restore-BCBenchRehearsalCheckpoint {
    param(
        [Parameter(Mandatory)][string]$ContainerName,
        [Parameter(Mandatory)][string]$ExpectedContainerId,
        [Parameter(Mandatory)][string]$ExpectedInvocationId,
        [Parameter(Mandatory)][PSObject]$Manifest,
        [Parameter(Mandatory)][PSCredential]$Credential,
        [Parameter(Mandatory)][string]$ExpectedCompany,
        [Parameter(Mandatory)][string]$StagingRoot,
        [Parameter(Mandatory)][ValidateSet("CorruptBackup", "ReadinessFailure", "UnexpectedApp", "ServiceRestartFailure")][string]$Fault,
        [int]$TimeoutSeconds = 900,
        [int]$PollIntervalSeconds = 5,
        [Parameter(DontShow)][hashtable]$Operations = @{}
    )
    Assert-BCBenchContainerOwnership -ContainerName $ContainerName -ExpectedContainerId $ExpectedContainerId `
        -ExpectedInvocationId $ExpectedInvocationId -Operations $Operations | Out-Null
    $injected = $Operations.Clone()
    if ($Fault -eq "CorruptBackup") {
        $backup = Resolve-BCBenchAbsolutePath -Path $Manifest.backup_path
        Assert-BCBenchNoReparseComponents -Path $backup
        if (-not (Test-BCBenchPathContains -Ancestor $StagingRoot -Path $backup) -or $backup -eq $StagingRoot) {
            throw "Refusing to corrupt a backup outside owned staging."
        }
        [IO.File]::AppendAllText($backup, "rehearsal-corruption")
    }
    elseif ($Fault -eq "UnexpectedApp") {
        $Manifest = $Manifest.PSObject.Copy()
        $Manifest.apps = @($Manifest.apps | Select-Object -Skip 1)
    }
    elseif ($Fault -eq "ReadinessFailure") {
        $injected.TestReadiness = {
            param($c)
            [PSCustomObject]@{ company_endpoint_ready = $false; test_discovery_ready = $true; test_count = 0 }
        }
    }
    elseif ($Fault -eq "ServiceRestartFailure") {
        $injected.StartServiceTier = {
            param($c)
            [PSCustomObject]@{ restarted = $false }
        }
    }
    return Restore-BCBenchCheckpoint -ContainerName $ContainerName -ExpectedContainerId $ExpectedContainerId `
        -ExpectedInvocationId $ExpectedInvocationId -Manifest $Manifest -Credential $Credential -ExpectedCompany $ExpectedCompany `
        -TimeoutSeconds $TimeoutSeconds -PollIntervalSeconds $PollIntervalSeconds -Operations $injected
}

Export-ModuleMember -Function Invoke-BCBenchRehearsalProbe, Get-BCBenchRehearsalDiscovery, Uninstall-BCBenchRehearsalTestApp, Restore-BCBenchRehearsalCheckpoint
