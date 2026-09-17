Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:BcContainerHelperVersion = [version]"6.1.18"
$script:UsersGroupSid = "S-1-5-32-545"
$script:AdministratorsGroupSid = "S-1-5-32-544"
$script:SystemSid = "S-1-5-18"
$script:LifecycleInvocationLabel = "bcbench.lifecycle.invocation"
$script:AgentDirectoryDenyMask = "(OI)(CI)(WD,AD,WEA,WA,DE,DC,WDAC,WO)"
$script:AgentDirectoryDenyRights = "WriteData, AppendData, WriteExtendedAttributes, WriteAttributes, Delete, DeleteSubdirectoriesAndFiles, ChangePermissions, TakeOwnership"
$script:AgentFileDenyMask = "(WD,AD,WEA,WA,DE,WDAC,WO)"
$script:AgentFileDenyRights = "WriteData, AppendData, WriteExtendedAttributes, WriteAttributes, Delete, ChangePermissions, TakeOwnership"

function Write-BCBenchSecretMask {
    param([AllowEmptyString()][string]$Secret)

    if ($env:GITHUB_ACTIONS -eq "true" -and -not [string]::IsNullOrEmpty($Secret)) {
        Write-Host "::add-mask::$Secret"
    }
}

function ConvertFrom-BCBenchSecureString {
    param([Parameter(Mandatory = $true)][SecureString]$SecureString)

    return ([PSCredential]::new("ignored", $SecureString)).GetNetworkCredential().Password
}

function New-BCBenchPassword {
    param([int]$Length = 32)

    if ($Length -lt 16) {
        throw "Password length must be at least 16 characters."
    }

    [char[]]$upper = "ABCDEFGHJKLMNPQRSTUVWXYZ".ToCharArray()
    [char[]]$lower = "abcdefghijkmnopqrstuvwxyz".ToCharArray()
    [char[]]$digits = "23456789".ToCharArray()
    [char[]]$special = "!@#%+=_-".ToCharArray()
    [char[]]$alphabet = $upper + $lower + $digits + $special
    [System.Collections.Generic.List[char]]$characters = [System.Collections.Generic.List[char]]::new()
    foreach ($set in @($upper, $lower, $digits, $special)) {
        $characters.Add($set[[Security.Cryptography.RandomNumberGenerator]::GetInt32($set.Length)])
    }
    while ($characters.Count -lt $Length) {
        $characters.Add($alphabet[[Security.Cryptography.RandomNumberGenerator]::GetInt32($alphabet.Length)])
    }
    for ($index = $characters.Count - 1; $index -gt 0; $index--) {
        $swapIndex = [Security.Cryptography.RandomNumberGenerator]::GetInt32($index + 1)
        ($characters[$index], $characters[$swapIndex]) = ($characters[$swapIndex], $characters[$index])
    }
    return -join $characters
}

function Get-BCBenchEntryHash {
    param([Parameter(Mandatory = $true)][string]$InstanceId)

    [byte[]]$bytes = [Text.Encoding]::UTF8.GetBytes($InstanceId)
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).Substring(0, 7).ToLowerInvariant()
}

function New-BCBenchScopedUsername {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("bcb", "bca")][string]$Prefix,
        [Parameter(Mandatory = $true)][string]$InstanceId
    )

    $random = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(3)).ToLowerInvariant()
    return "$Prefix-$(Get-BCBenchEntryHash -InstanceId $InstanceId)-$random"
}

function Assert-BCBenchAgentNotPrivileged {
    param([Parameter(Mandatory = $true)][string]$Username)

    $administrators = @(Get-LocalGroupMember -SID $script:AdministratorsGroupSid -ErrorAction SilentlyContinue)
    $dockerUsers = @(Get-LocalGroupMember -Group "docker-users" -ErrorAction SilentlyContinue)
    $privilegedMembers = @($administrators + $dockerUsers)
    if ($privilegedMembers | Where-Object { $_.Name -match "(^|\\)$([regex]::Escape($Username))$" }) {
        throw "Restricted identity '$Username' belongs to Administrators or docker-users."
    }
}

function Get-BCBenchLocalUser {
    param([Parameter(Mandatory = $true)][string]$Username)

    try {
        return Get-LocalUser -Name $Username -ErrorAction Stop
    }
    catch {
        $errorId = [string]$_.FullyQualifiedErrorId
        $reason = ($errorId -split ",", 2)[0]
        if (
            $_.CategoryInfo.Category -eq [Management.Automation.ErrorCategory]::ObjectNotFound -and
            $reason -eq "UserNotFound"
        ) {
            return $null
        }
        throw
    }
}

function New-BCBenchAgentIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$InstanceId,
        [ValidateRange(1, 50)][int]$MaxCollisionRetries = 10
    )

    for ($attempt = 1; $attempt -le $MaxCollisionRetries; $attempt++) {
        $username = New-BCBenchScopedUsername -Prefix bcb -InstanceId $InstanceId
        if ($null -ne (Get-BCBenchLocalUser -Username $username)) {
            continue
        }

        $password = New-BCBenchPassword
        $securePassword = ConvertTo-SecureString $password -AsPlainText -Force
        $createdUser = $false
        $localUser = $null
        $sid = $null
        try {
            $localUser = New-LocalUser `
                -Name $username `
                -Password $securePassword `
                -Description "BC-Bench restricted agent for $InstanceId" `
                -AccountNeverExpires `
                -PasswordNeverExpires
            $createdUser = $true
            Add-LocalGroupMember -SID $script:UsersGroupSid -Member $username
            Assert-BCBenchAgentNotPrivileged -Username $username
            $sidProperty = $localUser.PSObject.Properties["Sid"]
            $sid = if ($null -eq $sidProperty) { $null } else { [string]$sidProperty.Value }
            if ([string]::IsNullOrEmpty($sid)) {
                $sid = ([Security.Principal.NTAccount]::new(
                    [Environment]::MachineName,
                    $username
                )).Translate([Security.Principal.SecurityIdentifier]).Value
            }
        }
        catch {
            $creationFailure = $_.Exception
            if ($createdUser) {
                try {
                    Remove-LocalUser -Name $username -ErrorAction Stop
                }
                catch {
                    $failures = [System.Collections.Generic.List[Exception]]::new()
                    $failures.Add($creationFailure)
                    $failures.Add($_.Exception)
                    try {
                        Disable-LocalUser -Name $username -ErrorAction Stop
                    }
                    catch {
                        $failures.Add($_.Exception)
                    }
                    try {
                        Assert-BCBenchAgentIdentityDisabled -Username $username
                    }
                    catch {
                        $failures.Add($_.Exception)
                    }
                    throw [AggregateException]::new(
                        "Failed to create local agent identity '$username' and safely roll it back.",
                        $failures.ToArray()
                    )
                }
            }
            throw
        }

        Write-BCBenchSecretMask -Secret $password
        return [PSCustomObject]@{
            Username = $username
            Password = $password
            Domain   = [Environment]::MachineName
            Sid      = $sid
        }
    }

    throw "Unable to allocate a unique local agent identity after $MaxCollisionRetries attempts."
}

function Remove-BCBenchAgentIdentity {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Username)

    if ($Username -notmatch "^bcb-[a-f0-9]{7}-[a-f0-9]{6}$") {
        throw "Refusing to remove unexpected local username '$Username'."
    }
    if ($null -ne (Get-BCBenchLocalUser -Username $Username)) {
        Remove-LocalUser -Name $Username -ErrorAction Stop
    }
    if ($null -ne (Get-BCBenchLocalUser -Username $Username)) {
        throw "Local user '$Username' still exists after removal."
    }
}

function Disable-BCBenchAgentIdentity {
    param([Parameter(Mandatory = $true)][string]$Username)

    if ($Username -notmatch "^bcb-[a-f0-9]{7}-[a-f0-9]{6}$") {
        throw "Refusing to disable unexpected local username '$Username'."
    }
    $localUser = Get-BCBenchLocalUser -Username $Username
    if ($null -ne $localUser -and [bool]$localUser.Enabled) {
        Disable-LocalUser -Name $Username -ErrorAction Stop
    }
}

function Assert-BCBenchAgentIdentityDisabled {
    param([Parameter(Mandatory = $true)][string]$Username)

    if ($Username -notmatch "^bcb-[a-f0-9]{7}-[a-f0-9]{6}$") {
        throw "Refusing to verify unexpected local username '$Username'."
    }
    $localUser = Get-BCBenchLocalUser -Username $Username
    if ($null -ne $localUser -and [bool]$localUser.Enabled) {
        throw "Local user '$Username' remains enabled after disablement."
    }
}

function New-BCBenchAgentAclTransaction {
    param([Parameter(Mandatory = $true)][PSObject]$Identity)

    $sidProperty = $Identity.PSObject.Properties["Sid"]
    $sid = if ($null -eq $sidProperty) { $null } else { [string]$sidProperty.Value }
    if ([string]::IsNullOrEmpty($sid)) {
        $domain = if ([string]$Identity.Domain -eq ".") {
            [Environment]::MachineName
        }
        else {
            [string]$Identity.Domain
        }
        $sid = ([Security.Principal.NTAccount]::new(
            $domain,
            [string]$Identity.Username
        )).Translate([Security.Principal.SecurityIdentifier]).Value
    }
    if ($sid -notmatch "^S-\d(-\d+)+$") {
        throw "Restricted identity has an invalid SID '$sid'."
    }

    return [PSCustomObject]@{
        Sid             = $sid
        ModifiedPaths   = [System.Collections.Generic.List[string]]::new()
        CleanupComplete = $false
    }
}

function Add-BCBenchAgentAclPath {
    param(
        [Parameter(Mandatory = $true)][PSObject]$Transaction,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $absolute = Resolve-BCBenchAbsolutePath -Path $Path
    if (-not $Transaction.ModifiedPaths.Contains($absolute)) {
        $Transaction.ModifiedPaths.Add($absolute)
    }
}

function Assert-BCBenchAgentAclAbsent {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Sid
    )

    $acl = Get-Acl -LiteralPath $Path
    $remaining = @($acl.Access | Where-Object {
        Test-BCBenchAclIdentity -Actual $_.IdentityReference -Expected $Sid
    })
    if ($remaining.Count -gt 0) {
        throw "ACL cleanup verification failed for '$Path': $($remaining.Count) ACE(s) remain for SID '$Sid'."
    }
}

function Remove-BCBenchAgentAcl {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][PSObject]$Transaction,
        [Parameter(DontShow = $true)][scriptblock]$IcaclsRunner,
        [Parameter(DontShow = $true)][scriptblock]$AclVerifier
    )

    $sid = [string]$Transaction.Sid
    if ($sid -notmatch "^S-\d(-\d+)+$") {
        throw "Refusing ACL cleanup for invalid restricted identity SID '$sid'."
    }

    [System.Collections.Generic.List[string]]$cleanupErrors = [System.Collections.Generic.List[string]]::new()
    foreach ($path in $Transaction.ModifiedPaths | Select-Object -Unique) {
        if ($null -eq $IcaclsRunner -and -not (Test-Path -LiteralPath $path)) {
            continue
        }
        try {
            Invoke-BCBenchIcacls -Arguments @($path, "/remove:g", "*$sid") -Runner $IcaclsRunner
            Invoke-BCBenchIcacls -Arguments @($path, "/remove:d", "*$sid") -Runner $IcaclsRunner
            $verification = [PSCustomObject]@{
                Path = $path
                Sid  = $sid
            }
            if ($null -ne $AclVerifier) {
                & $AclVerifier $verification
            }
            else {
                Assert-BCBenchAgentAclAbsent -Path $path -Sid $sid
            }
        }
        catch {
            $cleanupErrors.Add("$path`: $($_.Exception.Message)")
        }
    }
    if ($cleanupErrors.Count -gt 0) {
        $Transaction.CleanupComplete = $false
        throw "Restricted identity ACL cleanup failed: $($cleanupErrors -join '; ')"
    }
    $Transaction.CleanupComplete = $true
}

function Resolve-BCBenchAbsolutePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [IO.Path]::GetFullPath($Path).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
}

function New-BCBenchAgentTools {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$EntryRoot,
        [Parameter(Mandatory = $true)][string]$BenchmarkRoot,
        [Parameter(Mandatory = $true)][string]$SourceWorkerPath
    )

    $entryRootPath = Resolve-BCBenchAbsolutePath -Path $EntryRoot
    $benchmarkRootPath = Resolve-BCBenchAbsolutePath -Path $BenchmarkRoot
    $sourceWorkerPathValue = Resolve-BCBenchAbsolutePath -Path $SourceWorkerPath
    $expectedSourceWorker = Join-Path $benchmarkRootPath "src\bcbench\agent\shared\contained_process_worker.py"
    if (-not $sourceWorkerPathValue.Equals(
        (Resolve-BCBenchAbsolutePath -Path $expectedSourceWorker),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Source worker must use the benchmark's exact contained process worker."
    }
    if (-not (Test-Path -LiteralPath $sourceWorkerPathValue -PathType Leaf)) {
        throw "Contained process source worker does not exist: $sourceWorkerPathValue"
    }
    Assert-BCBenchNoReparseComponents -Path $sourceWorkerPathValue

    $agentTools = Join-Path $entryRootPath "agent-tools"
    if (Test-BCBenchPathsOverlap -First $agentTools -Second $benchmarkRootPath) {
        throw "Agent tools must be outside the benchmark root."
    }
    if (-not (Test-Path -LiteralPath $entryRootPath -PathType Container)) {
        New-Item -ItemType Directory -Path $entryRootPath | Out-Null
    }
    Assert-BCBenchNoReparseComponents -Path $entryRootPath
    if (Test-Path -LiteralPath $agentTools) {
        throw "Agent tools path already exists: $agentTools"
    }
    New-Item -ItemType Directory -Path $agentTools | Out-Null
    Assert-BCBenchNoReparseComponents -Path $agentTools
    $workerPath = Join-Path $agentTools "contained_process_worker.py"
    Copy-Item -LiteralPath $sourceWorkerPathValue -Destination $workerPath
    $sourceHash = (Get-FileHash -LiteralPath $sourceWorkerPathValue -Algorithm SHA256).Hash.ToLowerInvariant()
    $workerHash = (Get-FileHash -LiteralPath $workerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($workerHash -ne $sourceHash) {
        throw "Staged contained process worker hash does not match its evaluator source."
    }

    return [PSCustomObject]@{
        AgentTools   = $agentTools
        WorkerPath   = $workerPath
        WorkerSha256 = $sourceHash
    }
}

function Test-BCBenchPathContains {
    param(
        [Parameter(Mandatory = $true)][string]$Ancestor,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $normalizedAncestor = Resolve-BCBenchAbsolutePath -Path $Ancestor
    $normalizedPath = Resolve-BCBenchAbsolutePath -Path $Path
    if ($normalizedPath.Equals($normalizedAncestor, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $normalizedPath.StartsWith(
        "$normalizedAncestor$([IO.Path]::DirectorySeparatorChar)",
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Test-BCBenchPathsOverlap {
    param(
        [Parameter(Mandatory = $true)][string]$First,
        [Parameter(Mandatory = $true)][string]$Second
    )

    return (Test-BCBenchPathContains -Ancestor $First -Path $Second) -or
        (Test-BCBenchPathContains -Ancestor $Second -Path $First)
}

function Resolve-BCBenchPythonRuntime {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$PythonExecutable)

    $runtimeProbe = @'
import json
import sys

print(json.dumps({
    "executable": sys.executable,
    "base_executable": getattr(sys, "_base_executable", sys.executable),
    "base_prefix": sys.base_prefix,
    "prefix": sys.prefix,
}))
'@
    $global:LASTEXITCODE = 0
    $output = & $PythonExecutable -c $runtimeProbe
    if (-not $?) {
        throw "Python runtime probe failed for '$PythonExecutable'."
    }
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "Python runtime probe failed for '$PythonExecutable' with exit code $LASTEXITCODE."
    }
    try {
        $runtime = (@($output)[-1] | ConvertFrom-Json -ErrorAction Stop)
    }
    catch {
        throw "Python runtime probe returned invalid JSON for '$PythonExecutable': $($_.Exception.Message)"
    }

    $paths = [ordered]@{
        Executable     = Resolve-BCBenchAbsolutePath -Path ([string]$runtime.executable)
        BaseExecutable = Resolve-BCBenchAbsolutePath -Path ([string]$runtime.base_executable)
        BasePrefix     = Resolve-BCBenchAbsolutePath -Path ([string]$runtime.base_prefix)
        Prefix         = Resolve-BCBenchAbsolutePath -Path ([string]$runtime.prefix)
    }
    foreach ($name in @("Executable", "BaseExecutable")) {
        if (-not (Test-Path -LiteralPath $paths[$name] -PathType Leaf)) {
            throw "Python runtime $name does not exist: $($paths[$name])"
        }
    }
    foreach ($name in @("BasePrefix", "Prefix")) {
        if (-not (Test-Path -LiteralPath $paths[$name] -PathType Container)) {
            throw "Python runtime $name does not exist: $($paths[$name])"
        }
    }
    if (-not (Test-BCBenchPathContains -Ancestor $paths.BasePrefix -Path $paths.BaseExecutable)) {
        throw "Python BaseExecutable must be contained by BasePrefix."
    }
    if (-not (Test-BCBenchPathContains -Ancestor $paths.Prefix -Path $paths.Executable)) {
        throw "Python Executable must be contained by Prefix."
    }

    return [PSCustomObject]$paths
}

function Assert-BCBenchReadExecuteRoots {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$ReadExecuteRoots,
        [Parameter(Mandatory = $true)][string]$BenchmarkRoot,
        [Parameter(Mandatory = $true)][string]$DatasetPath,
        [Parameter(Mandatory = $true)][string]$ProtectedRoot,
        [Parameter(Mandatory = $true)][string]$EntryRoot,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$AllowedAgentRoots,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$RestrictedLifecycleRoots
    )

    $restrictedPaths = @($BenchmarkRoot, $DatasetPath, $ProtectedRoot) + @($RestrictedLifecycleRoots)
    foreach ($readExecuteRoot in $ReadExecuteRoots | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $readExecuteRoot -PathType Container)) {
            throw "Read/execute root does not exist: $readExecuteRoot"
        }
        Assert-BCBenchNoReparseComponents -Path $readExecuteRoot
        if (Test-BCBenchPathsOverlap -First $readExecuteRoot -Second $EntryRoot) {
            $isAllowedAgentRoot = @($AllowedAgentRoots | Where-Object {
                Test-BCBenchPathContains -Ancestor $_ -Path $readExecuteRoot
            }).Count -gt 0
            if (-not $isAllowedAgentRoot) {
                throw "Read/execute root '$readExecuteRoot' must not overlap restricted benchmark or lifecycle paths outside agent workspace or logs."
            }
        }
        foreach ($restrictedPath in $restrictedPaths) {
            if (Test-BCBenchPathsOverlap -First $readExecuteRoot -Second $restrictedPath) {
                throw "Read/execute root '$readExecuteRoot' must not overlap restricted benchmark or lifecycle paths."
            }
        }
    }
}

function Assert-BCBenchNoReparseComponents {
    param([Parameter(Mandatory = $true)][string]$Path)

    $absolute = Resolve-BCBenchAbsolutePath -Path $Path
    $root = [IO.Path]::GetPathRoot($absolute)
    $relative = $absolute.Substring($root.Length)
    $current = $root
    foreach ($part in $relative.Split(
        [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar),
        [StringSplitOptions]::RemoveEmptyEntries
    )) {
        $current = Join-Path $current $part
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing symbolic link or reparse point: $current"
            }
        }
    }
}

function Assert-BCBenchLifecycleTopology {
    param(
        [Parameter(Mandatory = $true)][string]$EntryRoot,
        [Parameter(Mandatory = $true)][string]$ProtectedRoot,
        [Parameter(Mandatory = $true)][hashtable]$EntryPaths,
        [Parameter(Mandatory = $true)][hashtable]$ProtectedPaths
    )

    $entry = Resolve-BCBenchAbsolutePath -Path $EntryRoot
    $protected = Resolve-BCBenchAbsolutePath -Path $ProtectedRoot
    if ($entry -eq [IO.Path]::GetPathRoot($entry) -or $protected -eq [IO.Path]::GetPathRoot($protected)) {
        throw "EntryRoot and ProtectedRoot cannot be filesystem roots."
    }
    Assert-BCBenchNoReparseComponents -Path $entry
    Assert-BCBenchNoReparseComponents -Path $protected
    if ((Test-BCBenchPathContains -Ancestor $entry -Path $protected) -or (Test-BCBenchPathContains -Ancestor $protected -Path $entry)) {
        throw "EntryRoot and ProtectedRoot must be disjoint."
    }

    foreach ($collection in @(
        [PSCustomObject]@{ Root = $entry; Paths = $EntryPaths; RootName = "EntryRoot" },
        [PSCustomObject]@{ Root = $protected; Paths = $ProtectedPaths; RootName = "ProtectedRoot" }
    )) {
        foreach ($name in $collection.Paths.Keys) {
            $candidate = Resolve-BCBenchAbsolutePath -Path $collection.Paths[$name]
            Assert-BCBenchNoReparseComponents -Path $candidate
            if ($candidate.Equals($collection.Root, [StringComparison]::OrdinalIgnoreCase) -or -not (Test-BCBenchPathContains -Ancestor $collection.Root -Path $candidate)) {
                throw "$name must be a strict descendant of $($collection.RootName)."
            }
        }
        [string[]]$names = @($collection.Paths.Keys)
        for ($first = 0; $first -lt $names.Count; $first++) {
            for ($second = $first + 1; $second -lt $names.Count; $second++) {
                $firstPath = $collection.Paths[$names[$first]]
                $secondPath = $collection.Paths[$names[$second]]
                if ((Test-BCBenchPathContains -Ancestor $firstPath -Path $secondPath) -or (Test-BCBenchPathContains -Ancestor $secondPath -Path $firstPath)) {
                    throw "$($names[$first]) and $($names[$second]) must not contain each other."
                }
            }
        }
    }
}

function Invoke-BCBenchIcacls {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [scriptblock]$Runner
    )

    $exitCode = if ($null -ne $Runner) {
        & $Runner $Arguments
    }
    else {
        & icacls.exe @Arguments | Out-Host
        $LASTEXITCODE
    }
    if ($null -eq $exitCode -or [int]$exitCode -ne 0) {
        throw "icacls failed with exit code $exitCode for arguments: $($Arguments -join ' ')"
    }
}

function Get-BCBenchIcaclsGrant {
    param(
        [Parameter(Mandatory = $true)][PSObject]$Rule,
        [switch]$IsFile
    )

    $identity = [string]$Rule.Identity
    if ($identity -match "^S-\d(-\d+)+$") {
        $identity = "*$identity"
    }
    $permission = switch ([string]$Rule.Rights) {
        "FullControl" { "F" }
        "Modify" { "M" }
        "Read" { "R" }
        "ReadAndExecute" { "RX" }
        "Traverse" { "(X)" }
        default { throw "Unsupported icacls permission '$($Rule.Rights)'." }
    }
    $inheritance = if ($IsFile -or $permission -eq "(X)") { "" } else { "(OI)(CI)" }
    return "${identity}:$inheritance$permission"
}

function Test-BCBenchAclIdentity {
    param(
        [Parameter(Mandatory = $true)][Security.Principal.IdentityReference]$Actual,
        [Parameter(Mandatory = $true)][string]$Expected
    )

    if ($Actual.Value.Equals($Expected, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    try {
        $actualSid = $Actual.Translate([Security.Principal.SecurityIdentifier]).Value
        $expectedSid = if ($Expected -match "^S-\d(-\d+)+$") {
            $Expected
        }
        else {
            ([Security.Principal.NTAccount]::new($Expected)).Translate([Security.Principal.SecurityIdentifier]).Value
        }
        return $actualSid.Equals($expectedSid, [StringComparison]::OrdinalIgnoreCase)
    }
    catch {
        return $false
    }
}

function Assert-BCBenchAcl {
    param([Parameter(Mandatory = $true)][PSObject]$Parameters)

    $acl = Get-Acl -LiteralPath $Parameters.Path
    if ($Parameters.InheritanceRemoved -and -not $acl.AreAccessRulesProtected) {
        throw "ACL verification failed for '$($Parameters.Path)': inheritance is still enabled."
    }
    foreach ($expectedRule in $Parameters.ExpectedRules) {
        $expectedRights = [Security.AccessControl.FileSystemRights]$expectedRule.Rights
        $expectedType = if ($null -eq $expectedRule.PSObject.Properties["AccessControlType"]) {
            [Security.AccessControl.AccessControlType]::Allow
        }
        else {
            [Security.AccessControl.AccessControlType]$expectedRule.AccessControlType
        }
        $matchingRule = @($acl.Access | Where-Object {
            $_.AccessControlType -eq $expectedType -and
            (Test-BCBenchAclIdentity -Actual $_.IdentityReference -Expected ([string]$expectedRule.Identity)) -and
            ($_.FileSystemRights -band $expectedRights) -eq $expectedRights -and
            (
                $null -eq $expectedRule.PSObject.Properties["MustBeExplicit"] -or
                -not [bool]$expectedRule.MustBeExplicit -or
                -not $_.IsInherited
            ) -and
            (
                $null -eq $expectedRule.PSObject.Properties["InheritanceFlags"] -or
                $_.InheritanceFlags -eq [Security.AccessControl.InheritanceFlags]$expectedRule.InheritanceFlags
            )
        })
        if ($matchingRule.Count -eq 0) {
            throw "ACL verification failed for '$($Parameters.Path)': '$($expectedRule.Identity)' lacks '$($expectedRule.Rights)'."
        }
    }
    if ($Parameters.AgentMustBeAbsent) {
        $agentGrant = @($acl.Access | Where-Object {
            $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
            (Test-BCBenchAclIdentity -Actual $_.IdentityReference -Expected ([string]$Parameters.AgentAccount))
        })
        if ($agentGrant.Count -gt 0) {
            throw "ACL verification failed for '$($Parameters.Path)': agent grants remain."
        }
    }
}

function Set-BCBenchIdentityDeny {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$AgentAccount,
        [scriptblock]$IcaclsRunner,
        [scriptblock]$AclVerifier
    )

    Assert-BCBenchNoReparseComponents -Path $Path
    Invoke-BCBenchIcacls `
        -Arguments @($Path, "/deny", "${AgentAccount}:(OI)(CI)F") `
        -Runner $IcaclsRunner
    $verification = [PSCustomObject]@{
        Path               = $Path
        ExpectedRules      = @([PSCustomObject]@{
            Identity          = $AgentAccount
            Rights            = "FullControl"
            AccessControlType = "Deny"
        })
        AgentAccount       = $AgentAccount
        AgentMustBeAbsent  = $false
        InheritanceRemoved = $false
        IsFile             = $false
    }
    if ($null -ne $AclVerifier) {
        & $AclVerifier $verification
    }
    else {
        Assert-BCBenchAcl -Parameters $verification
    }
}

function Invoke-BCBenchReadExecuteDeny {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Sid,
        [switch]$IsFile,
        [scriptblock]$IcaclsRunner,
        [scriptblock]$AclVerifier
    )

    if ($Sid -notmatch "^S-\d(-\d+)+$") {
        throw "Restricted identity has an invalid SID '$Sid'."
    }
    Assert-BCBenchNoReparseComponents -Path $Path
    $denyMask = if ($IsFile) { $script:AgentFileDenyMask } else { $script:AgentDirectoryDenyMask }
    $denyRights = if ($IsFile) { $script:AgentFileDenyRights } else { $script:AgentDirectoryDenyRights }
    $inheritanceFlags = if ($IsFile) { "None" } else { "ContainerInherit, ObjectInherit" }
    Invoke-BCBenchIcacls `
        -Arguments @($Path, "/deny", "*${Sid}:$denyMask") `
        -Runner $IcaclsRunner
    $verification = [PSCustomObject]@{
        Path               = $Path
        ExpectedRules      = @([PSCustomObject]@{
            Identity          = $Sid
            Rights            = $denyRights
            AccessControlType = "Deny"
            MustBeExplicit    = $true
            InheritanceFlags  = $inheritanceFlags
        })
        AgentAccount       = $Sid
        AgentMustBeAbsent  = $false
        InheritanceRemoved = $false
        IsFile             = [bool]$IsFile
    }
    if ($null -ne $AclVerifier) {
        & $AclVerifier $verification
    }
    else {
        Assert-BCBenchAcl -Parameters $verification
    }
}

function Set-BCBenchExplicitAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object[]]$Rules,
        [Parameter(Mandatory = $true)][string]$AgentAccount,
        [switch]$IsFile,
        [switch]$RemoveAgent,
        [switch]$PreserveInheritance,
        [scriptblock]$IcaclsRunner,
        [scriptblock]$AclVerifier
    )

    Assert-BCBenchNoReparseComponents -Path $Path
    if (-not $PreserveInheritance) {
        Invoke-BCBenchIcacls -Arguments @($Path, "/inheritance:r") -Runner $IcaclsRunner
    }
    $grants = @($Rules | ForEach-Object { Get-BCBenchIcaclsGrant -Rule $_ -IsFile:$IsFile })
    Invoke-BCBenchIcacls -Arguments (@($Path, "/grant:r") + $grants) -Runner $IcaclsRunner
    if ($RemoveAgent) {
        Invoke-BCBenchIcacls -Arguments @($Path, "/remove:g", $AgentAccount) -Runner $IcaclsRunner
    }
    $verification = [PSCustomObject]@{
        Path               = $Path
        ExpectedRules      = @($Rules)
        AgentAccount       = $AgentAccount
        AgentMustBeAbsent  = [bool]$RemoveAgent
        InheritanceRemoved = -not $PreserveInheritance
        IsFile             = [bool]$IsFile
    }
    if ($null -ne $AclVerifier) {
        & $AclVerifier $verification
    }
    else {
        Assert-BCBenchAcl -Parameters $verification
    }
}

function Test-BCBenchIdentityAccess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][PSObject]$Identity,
        [Parameter(Mandatory = $true)][string]$AgentWorkspace,
        [Parameter(Mandatory = $true)][string]$AgentLogs,
        [Parameter(Mandatory = $true)][string]$MountedStaging,
        [Parameter(Mandatory = $true)][string]$ProtectedRoot,
        [Parameter(Mandatory = $true)][string]$BenchmarkRoot,
        [Parameter(Mandatory = $true)][string]$DatasetPath,
        [Parameter(Mandatory = $true)][string]$EvaluatorSourcePath,
        [Parameter(Mandatory = $true)][string]$DocsPath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$ReadExecuteDirectoryPaths,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$ReadExecuteFilePaths,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$RuntimeExecutablePaths,
        [string]$PythonExecutable = (Get-Command python -ErrorAction Stop).Source,
        [string]$ContainedProcessScriptPath = (Join-Path $PSScriptRoot "Invoke-ContainedProcess.ps1"),
        [string]$ContainedProcessWorkerPath = (Join-Path (Split-Path $PSScriptRoot -Parent) "src\bcbench\agent\shared\contained_process_worker.py"),
        [Parameter(Mandatory = $true)][ValidatePattern("^[a-fA-F0-9]{64}$")][string]$ContainedProcessWorkerSha256
    )

    $probeId = [guid]::NewGuid().ToString("N")
    $workspaceProbe = Join-Path $AgentWorkspace "identity-access-$probeId.txt"
    $protectedProbe = Join-Path $ProtectedRoot "identity-access-$probeId.txt"
    $protectedWriteProbe = Join-Path $ProtectedRoot "forbidden-$probeId.txt"
    $benchmarkWriteProbe = Join-Path $BenchmarkRoot "forbidden-$probeId.txt"
    $directoryProbes = [System.Collections.Generic.List[object]]::new()
    $probeRoot = Join-Path $MountedStaging ".identity-access-$probeId"
    $sharedPath = Join-Path $probeRoot "shared"
    New-Item -ItemType Directory -Path $sharedPath -Force | Out-Null
    $stagingProbe = [PSCustomObject]@{
        CreatePath = Join-Path $MountedStaging ".bcbench-create-$probeId.tmp"
        WritePath  = Join-Path $MountedStaging ".bcbench-write-$probeId.tmp"
        DeletePath = Join-Path $MountedStaging ".bcbench-delete-$probeId.tmp"
    }
    $outputParentProbe = [PSCustomObject]@{
        CreatePath = Join-Path $sharedPath ".bcbench-create-$probeId.tmp"
        WritePath  = Join-Path $sharedPath ".bcbench-write-$probeId.tmp"
        DeletePath = Join-Path $sharedPath ".bcbench-delete-$probeId.tmp"
    }
    try {
        [IO.File]::WriteAllText($protectedProbe, "evaluator-only", [Text.UTF8Encoding]::new($false))
        foreach ($probe in @($stagingProbe, $outputParentProbe)) {
            [IO.File]::WriteAllText($probe.WritePath, "write-probe", [Text.UTF8Encoding]::new($false))
            [IO.File]::WriteAllText($probe.DeletePath, "delete-probe", [Text.UTF8Encoding]::new($false))
        }
        foreach ($path in $ReadExecuteDirectoryPaths | Select-Object -Unique) {
            $directory = Resolve-BCBenchAbsolutePath -Path $path
            $probe = [PSCustomObject]@{
                Directory  = $directory
                CreatePath = Join-Path $directory ".bcbench-create-$probeId.tmp"
                WritePath  = Join-Path $directory ".bcbench-write-$probeId.tmp"
                DeletePath = Join-Path $directory ".bcbench-delete-$probeId.tmp"
            }
            $directoryProbes.Add($probe)
            [IO.File]::WriteAllText($probe.WritePath, "write-probe", [Text.UTF8Encoding]::new($false))
            [IO.File]::WriteAllText($probe.DeletePath, "delete-probe", [Text.UTF8Encoding]::new($false))
        }
    }
    catch {
        Remove-Item -LiteralPath $protectedProbe -Force -ErrorAction SilentlyContinue
        foreach ($probe in @($stagingProbe, $outputParentProbe)) {
            Remove-Item -LiteralPath $probe.CreatePath -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $probe.WritePath -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $probe.DeletePath -Force -ErrorAction SilentlyContinue
        }
        foreach ($probe in $directoryProbes) {
            Remove-Item -LiteralPath $probe.CreatePath -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $probe.WritePath -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $probe.DeletePath -Force -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
    $readExecuteFiles = @($ReadExecuteFilePaths | Select-Object -Unique | ForEach-Object {
        Resolve-BCBenchAbsolutePath -Path $_
    })
    $runtimeExecutables = @($RuntimeExecutablePaths | Select-Object -Unique | ForEach-Object {
        Resolve-BCBenchAbsolutePath -Path $_
    })

    $probeScript = @'
import ctypes
import json
import os
import subprocess
from pathlib import Path

workspace_error = None
protected_read_error = None
protected_write_error = None
benchmark_write_error = None
dataset_read_error = None
evaluator_source_read_error = None
docs_read_error = None
agent_tools_write_error = None
read_execute_directory_results = []
read_execute_file_results = []
runtime_executable_results = []
docker_cli_error = None
docker_pipe_error = None
output_file_open_error = None

try:
    Path(os.environ["BCBENCH_WORKSPACE_PROBE"]).write_text("agent-write", encoding="utf-8")
    workspace_write_succeeded = True
except OSError as error:
    workspace_write_succeeded = False
    workspace_error = str(error)

try:
    Path(os.environ["BCBENCH_PROTECTED_PROBE"]).read_text(encoding="utf-8")
    protected_read_denied = False
except PermissionError as error:
    protected_read_denied = True
    protected_read_error = str(error)

try:
    Path(os.environ["BCBENCH_PROTECTED_WRITE_PROBE"]).write_text("forbidden", encoding="utf-8")
    protected_write_denied = False
except PermissionError as error:
    protected_write_denied = True
    protected_write_error = str(error)

def denied_read(path):
    try:
        candidate = Path(path)
        if candidate.is_dir():
            next(candidate.iterdir(), None)
        else:
            candidate.read_bytes()
        return False, None
    except OSError as error:
        return True, str(error)

def denied_staging_operations(probe):
    result = {}
    try:
        Path(probe["CreatePath"]).write_text("forbidden", encoding="utf-8")
        result["CreateDenied"] = False
        result["CreateError"] = None
    except OSError as error:
        result["CreateDenied"] = True
        result["CreateError"] = str(error)

    try:
        with Path(probe["WritePath"]).open("ab") as probe_file:
            probe_file.write(b"forbidden")
        result["WriteDenied"] = False
        result["WriteError"] = None
    except OSError as error:
        result["WriteDenied"] = True
        result["WriteError"] = str(error)

    try:
        Path(probe["DeletePath"]).unlink()
        result["DeleteDenied"] = False
        result["DeleteError"] = None
    except OSError as error:
        result["DeleteDenied"] = True
        result["DeleteError"] = str(error)
    return result

dataset_read_denied, dataset_read_error = denied_read(os.environ["BCBENCH_DATASET_PROBE"])
evaluator_source_read_denied, evaluator_source_read_error = denied_read(os.environ["BCBENCH_EVALUATOR_SOURCE_PROBE"])
docs_read_denied, docs_read_error = denied_read(os.environ["BCBENCH_DOCS_PROBE"])
mounted_staging_result = denied_staging_operations(json.loads(os.environ["BCBENCH_MOUNTED_STAGING_PROBE"]))
output_parent_result = denied_staging_operations(json.loads(os.environ["BCBENCH_OUTPUT_PARENT_PROBE"]))

try:
    with Path(os.environ["BCBENCH_OUTPUT_FILE_PROBE"]).open("ab"):
        pass
    output_file_open_denied = False
except OSError as error:
    output_file_open_denied = True
    output_file_open_error = str(error)

try:
    Path(os.environ["BCBENCH_BENCHMARK_WRITE_PROBE"]).write_text("forbidden", encoding="utf-8")
    benchmark_write_denied = False
except OSError as error:
    benchmark_write_denied = True
    benchmark_write_error = str(error)

try:
    with Path(os.environ["BCBENCH_WORKER_PROBE"]).open("r+b"):
        pass
    agent_tools_write_denied = False
except OSError as error:
    agent_tools_write_denied = True
    agent_tools_write_error = str(error)

for probe in json.loads(os.environ["BCBENCH_READ_EXECUTE_DIRECTORY_PROBES"]):
    directory_result = {"Path": probe["Directory"]}
    try:
        next(Path(probe["Directory"]).iterdir(), None)
        directory_result["ReadSucceeded"] = True
        directory_result["ReadError"] = None
    except OSError as error:
        directory_result["ReadSucceeded"] = False
        directory_result["ReadError"] = str(error)

    try:
        Path(probe["CreatePath"]).write_text("forbidden", encoding="utf-8")
        directory_result["CreateDenied"] = False
        directory_result["CreateError"] = None
    except OSError as error:
        directory_result["CreateDenied"] = True
        directory_result["CreateError"] = str(error)

    try:
        with Path(probe["WritePath"]).open("ab") as probe_file:
            probe_file.write(b"forbidden")
        directory_result["WriteDenied"] = False
        directory_result["WriteError"] = None
    except OSError as error:
        directory_result["WriteDenied"] = True
        directory_result["WriteError"] = str(error)

    try:
        Path(probe["DeletePath"]).unlink()
        directory_result["DeleteDenied"] = False
        directory_result["DeleteError"] = None
    except OSError as error:
        directory_result["DeleteDenied"] = True
        directory_result["DeleteError"] = str(error)
    read_execute_directory_results.append(directory_result)

for path in json.loads(os.environ["BCBENCH_READ_EXECUTE_FILES"]):
    file_result = {"Path": path}
    try:
        with Path(path).open("rb") as probe_file:
            probe_file.read(1)
        file_result["ReadSucceeded"] = True
        file_result["ReadError"] = None
    except OSError as error:
        file_result["ReadSucceeded"] = False
        file_result["ReadError"] = str(error)

    try:
        with Path(path).open("r+b") as probe_file:
            original = probe_file.read(1)
            if original:
                probe_file.seek(0)
                probe_file.write(original)
                probe_file.flush()
        file_result["ModifyDenied"] = False
        file_result["ModifyError"] = None
    except OSError as error:
        file_result["ModifyDenied"] = True
        file_result["ModifyError"] = str(error)
    read_execute_file_results.append(file_result)

for path in json.loads(os.environ["BCBENCH_RUNTIME_EXECUTABLES"]):
    executable_result = {"Path": path}
    try:
        execution = subprocess.run(
            [path, "-c", "print('bcbench-runtime-ok')"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        executable_result["ExecutionSucceeded"] = (
            execution.returncode == 0
            and execution.stdout.strip() == "bcbench-runtime-ok"
        )
        executable_result["ExecutionError"] = (
            None
            if executable_result["ExecutionSucceeded"]
            else (execution.stdout + execution.stderr).strip()
        )
    except (OSError, subprocess.SubprocessError) as error:
        executable_result["ExecutionSucceeded"] = False
        executable_result["ExecutionError"] = str(error)
    runtime_executable_results.append(executable_result)

try:
    docker = subprocess.run(["docker", "version"], capture_output=True, text=True, timeout=15, check=False)
    docker_cli_denied = docker.returncode != 0
    if docker_cli_denied:
        docker_cli_error = (docker.stdout + docker.stderr).strip()
except (OSError, subprocess.SubprocessError) as error:
    docker_cli_denied = True
    docker_cli_error = str(error)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.argtypes = (
    ctypes.c_wchar_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
)
kernel32.CreateFileW.restype = ctypes.c_void_p
kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
kernel32.CloseHandle.restype = ctypes.c_int
pipe_handle = kernel32.CreateFileW(r"\\.\pipe\docker_engine", 0xC0000000, 0, None, 3, 0, None)
if pipe_handle == ctypes.c_void_p(-1).value:
    docker_pipe_denied = True
    docker_pipe_error = f"CreateFileW failed with error {ctypes.get_last_error()}"
else:
    docker_pipe_denied = False
    docker_pipe_error = "Connection unexpectedly succeeded"
    kernel32.CloseHandle(pipe_handle)

print(json.dumps({
    "WorkspaceWriteSucceeded": workspace_write_succeeded,
    "WorkspaceWriteError": workspace_error,
    "ProtectedReadDenied": protected_read_denied,
    "ProtectedReadError": protected_read_error,
    "ProtectedWriteDenied": protected_write_denied,
    "ProtectedWriteError": protected_write_error,
    "BenchmarkWriteDenied": benchmark_write_denied,
    "BenchmarkWriteError": benchmark_write_error,
    "DatasetReadDenied": dataset_read_denied,
    "DatasetReadError": dataset_read_error,
    "EvaluatorSourceReadDenied": evaluator_source_read_denied,
    "EvaluatorSourceReadError": evaluator_source_read_error,
    "DocsReadDenied": docs_read_denied,
    "DocsReadError": docs_read_error,
    "AgentToolsWriteDenied": agent_tools_write_denied,
    "AgentToolsWriteError": agent_tools_write_error,
    "ReadExecuteDirectoryReadSucceeded": all(
        result["ReadSucceeded"] for result in read_execute_directory_results
    ),
    "ReadExecuteDirectoryCreateDenied": all(
        result["CreateDenied"] for result in read_execute_directory_results
    ),
    "ReadExecuteDirectoryWriteDenied": all(
        result["WriteDenied"] for result in read_execute_directory_results
    ),
    "ReadExecuteDirectoryDeleteDenied": all(
        result["DeleteDenied"] for result in read_execute_directory_results
    ),
    "ReadExecuteFileReadSucceeded": all(
        result["ReadSucceeded"] for result in read_execute_file_results
    ),
    "ReadExecuteFileModifyDenied": all(
        result["ModifyDenied"] for result in read_execute_file_results
    ),
    "RuntimeExecutableExecutionSucceeded": all(
        result["ExecutionSucceeded"] for result in runtime_executable_results
    ),
    "ReadExecuteDirectoryResults": read_execute_directory_results,
    "ReadExecuteFileResults": read_execute_file_results,
    "RuntimeExecutableResults": runtime_executable_results,
    "MountedStagingCreateDenied": mounted_staging_result["CreateDenied"],
    "MountedStagingCreateError": mounted_staging_result["CreateError"],
    "MountedStagingWriteDenied": mounted_staging_result["WriteDenied"],
    "MountedStagingWriteError": mounted_staging_result["WriteError"],
    "MountedStagingDeleteDenied": mounted_staging_result["DeleteDenied"],
    "MountedStagingDeleteError": mounted_staging_result["DeleteError"],
    "OutputParentCreateDenied": output_parent_result["CreateDenied"],
    "OutputParentCreateError": output_parent_result["CreateError"],
    "OutputParentWriteDenied": output_parent_result["WriteDenied"],
    "OutputParentWriteError": output_parent_result["WriteError"],
    "OutputParentDeleteDenied": output_parent_result["DeleteDenied"],
    "OutputParentDeleteError": output_parent_result["DeleteError"],
    "OutputFileOpenDenied": output_file_open_denied,
    "OutputFileOpenError": output_file_open_error,
    "DockerCliDenied": docker_cli_denied,
    "DockerCliError": docker_cli_error,
    "DockerPipeDenied": docker_pipe_denied,
    "DockerPipeError": docker_pipe_error,
    "ProcessId": os.getpid(),
    "WorkspaceProbePath": os.environ["BCBENCH_WORKSPACE_PROBE"],
    "ProtectedProbePath": os.environ["BCBENCH_PROTECTED_PROBE"],
}, separators=(",", ":")))
'@
    $powershellExecutable = (Get-Process -Id $PID).Path
    $requestPath = Join-Path $probeRoot "request.json"
    $workerRequestPath = Join-Path $sharedPath "worker-request.json"
    $gatePath = Join-Path $sharedPath "launch.gate"
    $stdoutPath = Join-Path $sharedPath "stdout.txt"
    $stderrPath = Join-Path $sharedPath "stderr.txt"
    $request = @{
        command         = @($PythonExecutable, "-c", $probeScript)
        cwd             = $AgentWorkspace
        env             = @{
            PATH                            = $env:PATH
            PATHEXT                         = $env:PATHEXT
            SYSTEMROOT                      = $env:SYSTEMROOT
            COMSPEC                         = $env:COMSPEC
            TEMP                            = $AgentLogs
            TMP                             = $AgentLogs
            BCBENCH_WORKSPACE_PROBE         = $workspaceProbe
            BCBENCH_PROTECTED_PROBE         = $protectedProbe
            BCBENCH_PROTECTED_WRITE_PROBE   = $protectedWriteProbe
            BCBENCH_BENCHMARK_WRITE_PROBE   = $benchmarkWriteProbe
            BCBENCH_DATASET_PROBE            = $DatasetPath
            BCBENCH_EVALUATOR_SOURCE_PROBE   = $EvaluatorSourcePath
            BCBENCH_DOCS_PROBE               = $DocsPath
            BCBENCH_WORKER_PROBE             = $ContainedProcessWorkerPath
            BCBENCH_MOUNTED_STAGING_PROBE    = ($stagingProbe | ConvertTo-Json -Compress)
            BCBENCH_OUTPUT_PARENT_PROBE      = ($outputParentProbe | ConvertTo-Json -Compress)
            BCBENCH_OUTPUT_FILE_PROBE        = $stdoutPath
            BCBENCH_READ_EXECUTE_DIRECTORY_PROBES = ($directoryProbes | ConvertTo-Json -AsArray -Compress -Depth 4)
            BCBENCH_READ_EXECUTE_FILES       = ($readExecuteFiles | ConvertTo-Json -AsArray -Compress)
            BCBENCH_RUNTIME_EXECUTABLES      = ($runtimeExecutables | ConvertTo-Json -AsArray -Compress)
        }
        timeout_seconds = 20
        identity        = @{
            username = [string]$Identity.Username
            password = [string]$Identity.Password
            domain   = [string]$Identity.Domain
        }
    }
    $request | ConvertTo-Json -Compress -Depth 8 | Set-Content -LiteralPath $requestPath -Encoding utf8NoBOM

    try {
        $wrapperOutput = & $powershellExecutable `
            -NoLogo `
            -NoProfile `
            -NonInteractive `
            -File $ContainedProcessScriptPath `
            -RequestPath $requestPath `
            -WorkerRequestPath $workerRequestPath `
            -GatePath $gatePath `
            -StdoutPath $stdoutPath `
            -StderrPath $stderrPath `
            -PythonExecutable $PythonExecutable `
            -WorkerPath $ContainedProcessWorkerPath `
            -ExpectedWorkerSha256 $ContainedProcessWorkerSha256 `
            -WorkerStartupTimeoutSeconds 30 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Contained identity probe failed with wrapper exit code $LASTEXITCODE`: $(($wrapperOutput | Out-String).Trim())"
        }
        $wrapperResult = ($wrapperOutput | Out-String).Trim() | ConvertFrom-Json
        if ($wrapperResult.timed_out -or $wrapperResult.returncode -ne 0) {
            throw "Contained identity probe child failed: $($wrapperResult.stderr)"
        }
        $probeResult = ([string]$wrapperResult.stdout).Trim() | ConvertFrom-Json
        $probeResult | Add-Member -NotePropertyName OutputHandleCaptureSucceeded -NotePropertyValue $true
        return $probeResult
    }
    finally {
        Remove-Item -LiteralPath $workspaceProbe -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $protectedProbe -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $protectedWriteProbe -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $benchmarkWriteProbe -Force -ErrorAction SilentlyContinue
        foreach ($probe in @($stagingProbe, $outputParentProbe)) {
            Remove-Item -LiteralPath $probe.CreatePath -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $probe.WritePath -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $probe.DeletePath -Force -ErrorAction SilentlyContinue
        }
        foreach ($probe in $directoryProbes) {
            Remove-Item -LiteralPath $probe.CreatePath -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $probe.WritePath -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $probe.DeletePath -Force -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Set-BCBenchWorkspaceAcl {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][PSObject]$Identity,
        [Parameter(Mandatory = $true)][string]$EntryRoot,
        [Parameter(Mandatory = $true)][string]$BaselineWorkspace,
        [Parameter(Mandatory = $true)][string]$AgentWorkspace,
        [Parameter(Mandatory = $true)][string]$AgentLogs,
        [Parameter(Mandatory = $true)][string]$AgentTools,
        [Parameter(Mandatory = $true)][string]$MountedStaging,
        [Parameter(Mandatory = $true)][string]$EvaluatorWorkspaces,
        [Parameter(Mandatory = $true)][string]$Evidence,
        [Parameter(Mandatory = $true)][string]$ProtectedRoot,
        [Parameter(Mandatory = $true)][string]$BenchmarkRoot,
        [Parameter(Mandatory = $true)][string]$DatasetPath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$ToolRoots,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$RuntimeExecutablePaths,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$RuntimeRoots,
        [Parameter(Mandatory = $true)][string]$SourceWorkerPath,
        [Parameter(Mandatory = $true)][string]$WorkerPath,
        [Parameter(Mandatory = $true)][ValidatePattern("^[a-fA-F0-9]{64}$")][string]$WorkerSha256,
        [string[]]$WorkerRequestPaths = @(),
        [Parameter(DontShow = $true)][PSObject]$AclTransaction,
        [Parameter(DontShow = $true)][scriptblock]$IcaclsRunner,
        [Parameter(DontShow = $true)][scriptblock]$AclVerifier,
        [Parameter(DontShow = $true)][scriptblock]$AccessValidator
    )

    $entryPaths = @{
        BaselineWorkspace   = $BaselineWorkspace
        AgentWorkspace      = $AgentWorkspace
        AgentLogs           = $AgentLogs
        AgentTools          = $AgentTools
        MountedStaging      = $MountedStaging
        EvaluatorWorkspaces = $EvaluatorWorkspaces
        Evidence            = $Evidence
    }
    Assert-BCBenchLifecycleTopology `
        -EntryRoot $EntryRoot `
        -ProtectedRoot $ProtectedRoot `
        -EntryPaths $entryPaths `
        -ProtectedPaths @{}
    foreach ($requiredDirectory in @($EntryRoot, $ProtectedRoot) + @($entryPaths.Values)) {
        if (-not (Test-Path -LiteralPath $requiredDirectory -PathType Container)) {
            throw "Required ACL directory does not exist: $requiredDirectory"
        }
    }
    if (-not (Test-Path -LiteralPath $BenchmarkRoot -PathType Container)) {
        throw "Benchmark root does not exist: $BenchmarkRoot"
    }
    if (-not (Test-Path -LiteralPath $DatasetPath -PathType Leaf)) {
        throw "Dataset path does not exist: $DatasetPath"
    }
    $benchmarkRootPath = Resolve-BCBenchAbsolutePath -Path $BenchmarkRoot
    $datasetPathValue = Resolve-BCBenchAbsolutePath -Path $DatasetPath
    if (-not (Test-BCBenchPathContains -Ancestor $benchmarkRootPath -Path $datasetPathValue)) {
        throw "Dataset path must be contained by the benchmark root."
    }
    $evaluatorSourcePath = Join-Path $benchmarkRootPath "src\bcbench\evaluate"
    $docsPath = Join-Path $benchmarkRootPath "docs"
    foreach ($requiredBenchmarkDirectory in @($evaluatorSourcePath, $docsPath)) {
        if (-not (Test-Path -LiteralPath $requiredBenchmarkDirectory -PathType Container)) {
            throw "Required restricted benchmark directory does not exist: $requiredBenchmarkDirectory"
        }
    }
    $expectedSourceWorkerPath = Join-Path $benchmarkRootPath "src\bcbench\agent\shared\contained_process_worker.py"
    if (-not (Test-Path -LiteralPath $SourceWorkerPath -PathType Leaf)) {
        throw "Contained process source worker does not exist: $SourceWorkerPath"
    }
    if (-not (Resolve-BCBenchAbsolutePath -Path $SourceWorkerPath).Equals(
        (Resolve-BCBenchAbsolutePath -Path $expectedSourceWorkerPath),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Contained process source worker must use the benchmark's exact worker file path."
    }
    Assert-BCBenchNoReparseComponents -Path $SourceWorkerPath
    if (-not (Test-Path -LiteralPath $WorkerPath -PathType Leaf)) {
        throw "Contained process worker does not exist: $WorkerPath"
    }
    $expectedAgentTools = Join-Path (Resolve-BCBenchAbsolutePath -Path $EntryRoot) "agent-tools"
    if (-not (Resolve-BCBenchAbsolutePath -Path $AgentTools).Equals(
        (Resolve-BCBenchAbsolutePath -Path $expectedAgentTools),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Agent tools must use the entry root's exact agent-tools path."
    }
    $expectedStagedWorker = Join-Path $expectedAgentTools "contained_process_worker.py"
    if (
        -not (Resolve-BCBenchAbsolutePath -Path $WorkerPath).Equals(
            (Resolve-BCBenchAbsolutePath -Path $expectedStagedWorker),
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        (Test-BCBenchPathContains -Ancestor $benchmarkRootPath -Path $WorkerPath)
    ) {
        throw "Contained process worker must use the exact staged path inside agent tools and outside the benchmark root."
    }
    $sourceWorkerHash = (Get-FileHash -LiteralPath $SourceWorkerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $stagedWorkerHash = (Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($WorkerSha256.ToLowerInvariant() -ne $sourceWorkerHash -or $stagedWorkerHash -ne $sourceWorkerHash) {
        throw "Contained process staged worker hash does not match the evaluator source worker."
    }

    $restrictedLifecycleRoots = @(
        $BaselineWorkspace,
        $MountedStaging,
        $EvaluatorWorkspaces,
        $Evidence
    )
    Assert-BCBenchReadExecuteRoots `
        -ReadExecuteRoots (@($ToolRoots) + @($RuntimeRoots)) `
        -BenchmarkRoot $benchmarkRootPath `
        -DatasetPath $datasetPathValue `
        -ProtectedRoot $ProtectedRoot `
        -EntryRoot $EntryRoot `
        -AllowedAgentRoots @($AgentWorkspace, $AgentLogs, $AgentTools) `
        -RestrictedLifecycleRoots $restrictedLifecycleRoots
    foreach ($runtimeExecutablePath in $RuntimeExecutablePaths | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $runtimeExecutablePath -PathType Leaf)) {
            throw "Runtime executable does not exist: $runtimeExecutablePath"
        }
        Assert-BCBenchNoReparseComponents -Path $runtimeExecutablePath
        foreach ($restrictedPath in @($ProtectedRoot, $BaselineWorkspace, $MountedStaging, $EvaluatorWorkspaces, $Evidence, $datasetPathValue)) {
            if (Test-BCBenchPathsOverlap -First $runtimeExecutablePath -Second $restrictedPath) {
                throw "Runtime executable '$runtimeExecutablePath' must not overlap protected lifecycle paths."
            }
        }
        if (Test-BCBenchPathContains -Ancestor $benchmarkRootPath -Path $runtimeExecutablePath) {
            throw "Runtime executable must be outside the benchmark root."
        }
    }
    Assert-BCBenchNoReparseComponents -Path $WorkerPath
    foreach ($workerAccessPath in $WorkerRequestPaths) {
        if (-not (Test-Path -LiteralPath $workerAccessPath -PathType Leaf)) {
            throw "Worker access path must be an existing file: $workerAccessPath"
        }
        if ((Resolve-BCBenchAbsolutePath -Path $workerAccessPath).Equals(
            (Resolve-BCBenchAbsolutePath -Path $MountedStaging),
            [StringComparison]::OrdinalIgnoreCase
        ) -or -not (Test-BCBenchPathContains -Ancestor $MountedStaging -Path $workerAccessPath)) {
            throw "Worker access path must be a strict descendant of MountedStaging: $workerAccessPath"
        }
        Assert-BCBenchNoReparseComponents -Path $workerAccessPath
    }

    $agentAccount = if ([string]$Identity.Domain -eq ".") {
        "$([Environment]::MachineName)\$($Identity.Username)"
    }
    else {
        "$($Identity.Domain)\$($Identity.Username)"
    }
    $evaluatorAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $baseRules = @(
        [PSCustomObject]@{ Identity = $evaluatorAccount; Rights = "FullControl" },
        [PSCustomObject]@{ Identity = $script:SystemSid; Rights = "FullControl" }
    )
    $agentTraverse = [PSCustomObject]@{ Identity = $agentAccount; Rights = "Traverse" }
    $agentModify = [PSCustomObject]@{ Identity = $agentAccount; Rights = "Modify" }
    if ($null -eq $AclTransaction) {
        $AclTransaction = New-BCBenchAgentAclTransaction -Identity $Identity
    }
    $agentSid = [string]$AclTransaction.Sid

    try {
        Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $BenchmarkRoot
        Set-BCBenchIdentityDeny `
            -Path $BenchmarkRoot `
            -AgentAccount $agentAccount `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
        Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $EntryRoot
        Set-BCBenchExplicitAcl `
            -Path $EntryRoot `
            -Rules ($baseRules + $agentTraverse) `
            -AgentAccount $agentAccount `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
        foreach ($privatePath in @($BaselineWorkspace, $MountedStaging, $EvaluatorWorkspaces, $Evidence, $ProtectedRoot)) {
            Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $privatePath
            Set-BCBenchExplicitAcl `
                -Path $privatePath `
                -Rules $baseRules `
                -AgentAccount $agentAccount `
                -RemoveAgent `
                -IcaclsRunner $IcaclsRunner `
                -AclVerifier $AclVerifier
        }
        Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $AgentWorkspace
        Set-BCBenchExplicitAcl `
            -Path $AgentWorkspace `
            -Rules ($baseRules + $agentModify) `
            -AgentAccount $agentAccount `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
        Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $AgentLogs
        Set-BCBenchExplicitAcl `
            -Path $AgentLogs `
            -Rules ($baseRules + $agentModify) `
            -AgentAccount $agentAccount `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
        $agentRead = [PSCustomObject]@{ Identity = $agentAccount; Rights = "ReadAndExecute" }
        Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $AgentTools
        Set-BCBenchExplicitAcl `
            -Path $AgentTools `
            -Rules @($agentRead) `
            -AgentAccount $agentAccount `
            -PreserveInheritance `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
        Invoke-BCBenchReadExecuteDeny `
            -Path $AgentTools `
            -Sid $agentSid `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
        Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $WorkerPath
        Set-BCBenchExplicitAcl `
            -Path $WorkerPath `
            -Rules @($agentRead) `
            -AgentAccount $agentAccount `
            -IsFile `
            -PreserveInheritance `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
        Invoke-BCBenchReadExecuteDeny `
            -Path $WorkerPath `
            -Sid $agentSid `
            -IsFile `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
        foreach ($toolRoot in $ToolRoots | Select-Object -Unique) {
            $agentRead = [PSCustomObject]@{ Identity = $agentAccount; Rights = "ReadAndExecute" }
            Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $toolRoot
            Set-BCBenchExplicitAcl `
                -Path $toolRoot `
                -Rules @($agentRead) `
                -AgentAccount $agentAccount `
                -PreserveInheritance `
                -IcaclsRunner $IcaclsRunner `
                -AclVerifier $AclVerifier
            Invoke-BCBenchReadExecuteDeny `
                -Path $toolRoot `
                -Sid $agentSid `
                -IcaclsRunner $IcaclsRunner `
                -AclVerifier $AclVerifier
        }
        foreach ($runtimeRoot in $RuntimeRoots | Select-Object -Unique) {
            $agentRead = [PSCustomObject]@{ Identity = $agentAccount; Rights = "ReadAndExecute" }
            Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $runtimeRoot
            Set-BCBenchExplicitAcl `
                -Path $runtimeRoot `
                -Rules @($agentRead) `
                -AgentAccount $agentAccount `
                -PreserveInheritance `
                -IcaclsRunner $IcaclsRunner `
                -AclVerifier $AclVerifier
            Invoke-BCBenchReadExecuteDeny `
                -Path $runtimeRoot `
                -Sid $agentSid `
                -IcaclsRunner $IcaclsRunner `
                -AclVerifier $AclVerifier
        }
        foreach ($runtimeExecutablePath in $RuntimeExecutablePaths | Select-Object -Unique) {
            $agentRead = [PSCustomObject]@{ Identity = $agentAccount; Rights = "ReadAndExecute" }
            Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $runtimeExecutablePath
            Set-BCBenchExplicitAcl `
                -Path $runtimeExecutablePath `
                -Rules @($agentRead) `
                -AgentAccount $agentAccount `
                -IsFile `
                -PreserveInheritance `
                -IcaclsRunner $IcaclsRunner `
                -AclVerifier $AclVerifier
            Invoke-BCBenchReadExecuteDeny `
                -Path $runtimeExecutablePath `
                -Sid $agentSid `
                -IsFile `
                -IcaclsRunner $IcaclsRunner `
                -AclVerifier $AclVerifier
        }
        if ($WorkerRequestPaths.Count -gt 0) {
            Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $MountedStaging
            Set-BCBenchExplicitAcl `
                -Path $MountedStaging `
                -Rules ($baseRules + $agentTraverse) `
                -AgentAccount $agentAccount `
                -IcaclsRunner $IcaclsRunner `
                -AclVerifier $AclVerifier
        }
        foreach ($requestPath in $WorkerRequestPaths) {
            $agentRead = [PSCustomObject]@{ Identity = $agentAccount; Rights = "Read" }
            Add-BCBenchAgentAclPath -Transaction $AclTransaction -Path $requestPath
            Set-BCBenchExplicitAcl `
                -Path $requestPath `
                -Rules @($agentRead) `
                -AgentAccount $agentAccount `
                -IsFile `
                -PreserveInheritance `
                -IcaclsRunner $IcaclsRunner `
                -AclVerifier $AclVerifier
            Invoke-BCBenchReadExecuteDeny `
                -Path $requestPath `
                -Sid $agentSid `
                -IsFile `
                -IcaclsRunner $IcaclsRunner `
                -AclVerifier $AclVerifier
        }

        $validationParameters = @{
            Identity                     = $Identity
            AgentWorkspace               = $AgentWorkspace
            AgentLogs                    = $AgentLogs
            MountedStaging               = $MountedStaging
            ProtectedRoot                = $ProtectedRoot
            BenchmarkRoot                = $BenchmarkRoot
            DatasetPath                  = $DatasetPath
            EvaluatorSourcePath          = $evaluatorSourcePath
            DocsPath                     = $docsPath
            ReadExecuteDirectoryPaths    = @($AgentTools) + @($ToolRoots) + @($RuntimeRoots)
            ReadExecuteFilePaths         = @($WorkerPath) + @($RuntimeExecutablePaths) + @($WorkerRequestPaths)
            RuntimeExecutablePaths       = @($RuntimeExecutablePaths)
            PythonExecutable             = @($RuntimeExecutablePaths)[0]
            ContainedProcessWorkerPath   = $WorkerPath
            ContainedProcessWorkerSha256 = $WorkerSha256
        }
        $result = if ($null -ne $AccessValidator) {
            & $AccessValidator $validationParameters
        }
        else {
            Test-BCBenchIdentityAccess @validationParameters
        }
        foreach ($property in @(
            "WorkspaceWriteSucceeded",
            "ProtectedReadDenied",
            "ProtectedWriteDenied",
            "BenchmarkWriteDenied",
            "DatasetReadDenied",
            "EvaluatorSourceReadDenied",
            "DocsReadDenied",
            "AgentToolsWriteDenied",
            "ReadExecuteDirectoryReadSucceeded",
            "ReadExecuteDirectoryCreateDenied",
            "ReadExecuteDirectoryWriteDenied",
            "ReadExecuteDirectoryDeleteDenied",
            "ReadExecuteFileReadSucceeded",
            "ReadExecuteFileModifyDenied",
            "RuntimeExecutableExecutionSucceeded",
            "MountedStagingCreateDenied",
            "MountedStagingWriteDenied",
            "MountedStagingDeleteDenied",
            "OutputParentCreateDenied",
            "OutputParentWriteDenied",
            "OutputParentDeleteDenied",
            "OutputFileOpenDenied",
            "OutputHandleCaptureSucceeded",
            "DockerCliDenied",
            "DockerPipeDenied"
        )) {
            if (-not [bool]$result.$property) {
                throw "Restricted identity access verification failed: $property was false."
            }
        }
        $result | Add-Member -NotePropertyName AclTransaction -NotePropertyValue $AclTransaction -Force
        return $result
    }
    catch {
        $originalError = $_
        try {
            Remove-BCBenchAgentAcl `
                -Transaction $AclTransaction `
                -IcaclsRunner $IcaclsRunner `
                -AclVerifier $AclVerifier
        }
        catch {
            throw "$($originalError.Exception.Message) ACL rollback errors: $($_.Exception.Message)"
        }
        throw $originalError
    }
}

function New-BCBenchAgentBcUser {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$InstanceId,
        [Parameter(Mandatory = $true)][string]$ContainerName
    )

    Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
    $username = New-BCBenchScopedUsername -Prefix bca -InstanceId $InstanceId
    $password = New-BCBenchPassword
    $credential = [PSCredential]::new($username, (ConvertTo-SecureString $password -AsPlainText -Force))
    New-BcContainerBcUser `
        -containerName $ContainerName `
        -Credential $credential `
        -PermissionSetId SUPER `
        -ChangePasswordAtNextLogOn $false
    Write-BCBenchSecretMask -Secret $password
    return [PSCustomObject]@{
        Username = $username
        Password = $password
    }
}

function Invoke-BCBenchAgentBcUserRemoval {
    param(
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][string]$Username
    )

    Invoke-ScriptInBcContainer -containerName $ContainerId -ScriptBlock {
        param([string]$Username)

        $serverInstance = (Get-NAVServerInstance | Select-Object -First 1).ServerInstance
        $existingUser = @(Get-NAVServerUser -ServerInstance $serverInstance -Tenant "default") |
            Where-Object { $_.'User Name' -eq $Username }
        if ($null -eq $existingUser) {
            return
        }
        Remove-NAVServerUser -ServerInstance $serverInstance -Tenant "default" -UserName $Username -Force
        if ($null -ne (@(Get-NAVServerUser -ServerInstance $serverInstance -Tenant "default") |
                Where-Object { $_.'User Name' -eq $Username })) {
            throw "BC user '$Username' still exists after removal."
        }
    } -ArgumentList $Username
}

function Assert-BCBenchAgentBcUserAbsent {
    param(
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][string]$Username
    )

    Invoke-ScriptInBcContainer -containerName $ContainerId -ScriptBlock {
        param([string]$Username)

        $serverInstance = (Get-NAVServerInstance | Select-Object -First 1).ServerInstance
        if ($null -ne (@(Get-NAVServerUser -ServerInstance $serverInstance -Tenant "default") |
                Where-Object { $_.'User Name' -eq $Username })) {
            throw "BC user '$Username' still exists after removal."
        }
    } -ArgumentList $Username
}

function Remove-BCBenchAgentBcUser {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ContainerName,
        [Parameter(Mandatory = $true)][string]$Username,
        [Parameter(Mandatory = $true)][string]$ExpectedContainerId,
        [Parameter(Mandatory = $true)][string]$ExpectedInvocationId,
        [Parameter(DontShow = $true)][hashtable]$Operations = @{}
    )

    if ($Username -notmatch "^bca-[a-f0-9]{7}-[a-f0-9]{6}$") {
        throw "Refusing to remove unexpected BC username '$Username'."
    }
    Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
    $context = [PSCustomObject]@{
        ContainerName         = $ContainerName
        ContainerId           = $ExpectedContainerId
        ContainerInvocationId = $ExpectedInvocationId
        VerifiedContainerId   = $null
    }
    $verifiedContainerId = Get-BCBenchVerifiedContainerId -Operations $Operations -Context $context
    Invoke-BCBenchAgentBcUserRemoval -ContainerId $verifiedContainerId -Username $Username
}

function Invoke-BCBenchOperation {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Operations,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][PSObject]$Context,
        [Parameter(Mandatory = $true)][scriptblock]$Default
    )

    if ($Operations.ContainsKey($Name)) {
        return & $Operations[$Name] $Context
    }
    return & $Default $Context
}

function Get-BCBenchContainerState {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$ContainerName)

    $global:LASTEXITCODE = 0
    $output = & docker container inspect --format "{{json .}}" $ContainerName 2>&1
    $exitCode = $LASTEXITCODE
    $text = (@($output) -join [Environment]::NewLine).Trim()
    if ($exitCode -ne 0) {
        if ($text -match "(?i)no such (object|container)") {
            return [PSCustomObject]@{
                Exists       = $false
                Id           = $null
                InvocationId = $null
            }
        }
        throw "Docker inspect failed for container '$ContainerName' with exit code $exitCode`: $text"
    }
    try {
        $container = $text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Docker inspect returned invalid JSON for container '$ContainerName': $($_.Exception.Message)"
    }
    $invocationId = $null
    if ($null -ne $container.Config.Labels) {
        $label = $container.Config.Labels.PSObject.Properties[$script:LifecycleInvocationLabel]
        if ($null -ne $label) {
            $invocationId = [string]$label.Value
        }
    }
    return [PSCustomObject]@{
        Exists       = $true
        Id           = [string]$container.Id
        InvocationId = $invocationId
    }
}

function Get-BCBenchVerifiedContainerId {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Operations,
        [Parameter(Mandatory = $true)][PSObject]$Context
    )

    if (
        [string]::IsNullOrEmpty([string]$Context.ContainerId) -or
        [string]::IsNullOrEmpty([string]$Context.ContainerInvocationId)
    ) {
        throw "Refusing container-scoped cleanup because recorded ownership is incomplete."
    }
    $state = Invoke-BCBenchOperation -Operations $Operations -Name InspectContainer -Context $Context -Default {
        param($operationContext)
        return Get-BCBenchContainerState -ContainerName $operationContext.ContainerName
    }
    if (-not [bool]$state.Exists) {
        throw "Refusing container-scoped cleanup because owned container '$($Context.ContainerName)' is missing."
    }
    if ([string]$state.InvocationId -ne [string]$Context.ContainerInvocationId) {
        throw "Refusing container-scoped cleanup for container '$($Context.ContainerName)' with a missing or different lifecycle invocation label."
    }
    if ([string]::IsNullOrEmpty([string]$state.Id)) {
        throw "Refusing container-scoped cleanup for container '$($Context.ContainerName)' without a Docker ID."
    }
    if ([string]$state.Id -ne [string]$Context.ContainerId) {
        throw "Refusing container-scoped cleanup for container '$($Context.ContainerName)' because its Docker ID changed."
    }

    $Context.VerifiedContainerId = [string]$state.Id
    return $Context.VerifiedContainerId
}

function Get-BCBenchContainerStateById {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Operations,
        [Parameter(Mandatory = $true)][PSObject]$Context
    )

    $inspectionContext = $Context.PSObject.Copy()
    $inspectionContext | Add-Member -NotePropertyName InspectionTarget -NotePropertyValue $Context.ContainerId -Force
    if ($Operations.ContainsKey("InspectContainerById")) {
        return & $Operations["InspectContainerById"] $inspectionContext
    }
    if ($Operations.ContainsKey("InspectContainer")) {
        $inspectionContext.ContainerName = $Context.ContainerId
        return & $Operations["InspectContainer"] $inspectionContext
    }
    return Get-BCBenchContainerState -ContainerName $Context.ContainerId
}

function Assert-BCBenchContainerAbsent {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Operations,
        [Parameter(Mandatory = $true)][PSObject]$Context
    )

    [System.Collections.Generic.List[string]]$remainingContainers = [System.Collections.Generic.List[string]]::new()
    $nameState = Invoke-BCBenchOperation -Operations $Operations -Name InspectContainer -Context $Context -Default {
        param($operationContext)
        return Get-BCBenchContainerState -ContainerName $operationContext.ContainerName
    }
    if ([bool]$nameState.Exists) {
        $remainingContainers.Add("container name '$($Context.ContainerName)' with Docker ID '$($nameState.Id)'")
    }
    if (-not [string]::IsNullOrEmpty([string]$Context.ContainerId)) {
        $idState = Get-BCBenchContainerStateById -Operations $Operations -Context $Context
        if ([bool]$idState.Exists) {
            $remainingContainers.Add("container Docker ID '$($Context.ContainerId)'")
        }
    }
    if ($remainingContainers.Count -gt 0) {
        throw "$($remainingContainers -join ' and ') still exists after removal."
    }
}

function New-BCBenchInvocationId {
    return [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(16)).ToLowerInvariant()
}

function Get-BCBenchQuarantinePath {
    param([Parameter(Mandatory = $true)][string]$ProtectedRoot)

    $parent = Split-Path -Parent $ProtectedRoot
    $leaf = Split-Path -Leaf $ProtectedRoot
    return Join-Path $parent "$leaf.quarantine.json"
}

function Write-BCBenchCleanupQuarantine {
    param(
        [Parameter(Mandatory = $true)][PSObject]$Context,
        [Parameter(Mandatory = $true)][string]$OriginalError,
        [Parameter(Mandatory = $true)][string[]]$CleanupErrors
    )

    $path = Get-BCBenchQuarantinePath -ProtectedRoot $Context.ProtectedRoot
    $payload = [ordered]@{
        instance_id             = $Context.InstanceId
        container_name          = $Context.ContainerName
        expected_container_id   = $Context.ContainerId
        expected_invocation_id  = $Context.ContainerInvocationId
        entry_root              = $Context.EntryRoot
        protected_root          = $Context.ProtectedRoot
        local_username          = if ($null -eq $Context.AgentIdentity) { $null } else { $Context.AgentIdentity.Username }
        local_sid               = if ($null -eq $Context.AclTransaction) { $null } else { $Context.AclTransaction.Sid }
        original_error          = $OriginalError
        cleanup_errors          = @($CleanupErrors)
        created_at_utc          = [DateTime]::UtcNow.ToString("o")
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding utf8 -ErrorAction Stop
    return $path
}

function Remove-BCBenchCreatedRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $absolute = Resolve-BCBenchAbsolutePath -Path $Path
    if ($absolute -eq [IO.Path]::GetPathRoot($absolute)) {
        throw "Refusing to remove filesystem root '$absolute'."
    }
    Assert-BCBenchNoReparseComponents -Path $absolute
    if (Test-Path -LiteralPath $absolute) {
        [System.Collections.Generic.Stack[string]]$directories = [System.Collections.Generic.Stack[string]]::new()
        $directories.Push($absolute)
        while ($directories.Count -gt 0) {
            $directory = $directories.Pop()
            foreach ($child in [IO.Directory]::EnumerateFileSystemEntries($directory)) {
                $attributes = [IO.File]::GetAttributes($child)
                if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                    throw "Refusing to remove managed root containing a reparse point: $child"
                }
                if (($attributes -band [IO.FileAttributes]::Directory) -ne 0) {
                    $directories.Push($child)
                }
            }
        }
        Remove-Item -LiteralPath $absolute -Recurse -Force -ErrorAction Stop
    }
}

function Add-BCBenchOutput {
    param(
        [string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value
    )

    if (-not [string]::IsNullOrEmpty($Path)) {
        "$Name=$Value" | Out-File -LiteralPath $Path -Append -Encoding utf8
    }
}

function Invoke-BCBenchBugFixLifecycle {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$InstanceId,
        [ValidateSet("bug-fix")][string]$Category = "bug-fix",
        [Parameter(Mandatory = $true)][string]$DatasetPath,
        [string]$Version,
        [string]$Country = "w1",
        [Parameter(Mandatory = $true)][string]$ContainerName,
        [Parameter(Mandatory = $true)][string]$EvaluatorUsername,
        [Parameter(Mandatory = $true)][SecureString]$EvaluatorPassword,
        [Parameter(Mandatory = $true)][string]$EntryRoot,
        [Parameter(Mandatory = $true)][string]$ProtectedRoot,
        [string]$BenchmarkRoot = (Split-Path $PSScriptRoot -Parent),
        [string]$PythonExecutable = (Get-Command python -ErrorAction Stop).Source,
        [string]$PythonBaseExecutable,
        [string]$PythonBasePrefix,
        [string]$PythonPrefix,
        [string]$WorkerPath = (Join-Path (Split-Path $PSScriptRoot -Parent) "src\bcbench\agent\shared\contained_process_worker.py"),
        [string[]]$ToolRoots = @(),
        [switch]$AlMcp,
        [switch]$BcMcp,
        [string]$GithubToken,
        [string]$AdoToken,
        [string]$GithubOutput = $env:GITHUB_OUTPUT,
        [string]$GithubEnv = $env:GITHUB_ENV,
        [Parameter(DontShow = $true)][hashtable]$Operations = @{}
    )

    $entryRootPath = Resolve-BCBenchAbsolutePath -Path $EntryRoot
    $protectedRootPath = Resolve-BCBenchAbsolutePath -Path $ProtectedRoot
    $benchmarkRootPath = Resolve-BCBenchAbsolutePath -Path $BenchmarkRoot
    if (
        [string]::IsNullOrEmpty($PythonBaseExecutable) -or
        [string]::IsNullOrEmpty($PythonBasePrefix) -or
        [string]::IsNullOrEmpty($PythonPrefix)
    ) {
        $pythonRuntime = Resolve-BCBenchPythonRuntime -PythonExecutable $PythonExecutable
        $PythonExecutable = $pythonRuntime.Executable
        $PythonBaseExecutable = $pythonRuntime.BaseExecutable
        $PythonBasePrefix = $pythonRuntime.BasePrefix
        $PythonPrefix = $pythonRuntime.Prefix
    }
    $entryPaths = @{
        BaselineWorkspace   = Join-Path $entryRootPath "baseline-workspace"
        AgentWorkspace      = Join-Path $entryRootPath "agent-workspace"
        AgentLogs           = Join-Path $entryRootPath "agent-logs"
        AgentTools          = Join-Path $entryRootPath "agent-tools"
        MountedStaging      = Join-Path $entryRootPath "mounted-staging"
        EvaluatorWorkspaces = Join-Path $entryRootPath "evaluator-workspaces"
        Evidence            = Join-Path $entryRootPath "evidence"
    }
    $protectedPaths = @{
        TrustedSource = Join-Path $protectedRootPath "trusted-source"
        Checkpoints   = Join-Path $protectedRootPath "checkpoints"
        FinalResults  = Join-Path $protectedRootPath "final-results"
    }
    Assert-BCBenchLifecycleTopology `
        -EntryRoot $entryRootPath `
        -ProtectedRoot $protectedRootPath `
        -EntryPaths $entryPaths `
        -ProtectedPaths $protectedPaths
    if ((Test-Path -LiteralPath $entryRootPath) -or (Test-Path -LiteralPath $protectedRootPath)) {
        throw "EntryRoot and ProtectedRoot must not already exist for a new lifecycle invocation."
    }

    $context = [PSCustomObject]@{
        InstanceId             = $InstanceId
        Category               = $Category
        DatasetPath            = $DatasetPath
        Version                = $Version
        Country                = $Country
        ContainerName          = $ContainerName
        EvaluatorUsername      = $EvaluatorUsername
        EvaluatorPassword      = $EvaluatorPassword
        EntryRoot              = $entryRootPath
        ProtectedRoot          = $protectedRootPath
        BenchmarkRoot          = $benchmarkRootPath
        PythonExecutable       = Resolve-BCBenchAbsolutePath -Path $PythonExecutable
        PythonBaseExecutable   = Resolve-BCBenchAbsolutePath -Path $PythonBaseExecutable
        PythonBasePrefix       = Resolve-BCBenchAbsolutePath -Path $PythonBasePrefix
        PythonPrefix           = Resolve-BCBenchAbsolutePath -Path $PythonPrefix
        SourceWorkerPath       = Resolve-BCBenchAbsolutePath -Path $WorkerPath
        WorkerPath             = $null
        WorkerSha256           = $null
        BaselineWorkspace      = $entryPaths.BaselineWorkspace
        AgentWorkspace         = $entryPaths.AgentWorkspace
        AgentLogs              = $entryPaths.AgentLogs
        AgentTools             = $entryPaths.AgentTools
        MountedStaging         = $entryPaths.MountedStaging
        EvaluatorWorkspaces    = $entryPaths.EvaluatorWorkspaces
        Evidence               = $entryPaths.Evidence
        TrustedSource          = $protectedPaths.TrustedSource
        Checkpoints            = $protectedPaths.Checkpoints
        FinalResults           = $protectedPaths.FinalResults
        ToolRoots              = @($ToolRoots)
        AlMcp                  = [bool]$AlMcp
        BcMcp                  = [bool]$BcMcp
        Entry                  = $null
        ArtifactUrl            = $null
        EvaluatorCredential    = $null
        AgentIdentity          = $null
        AgentBcIdentity        = $null
        AclTransaction         = $null
        EvaluatorContainerConfig = $null
        AgentContainerConfig     = $null
        ContainerInvocationId    = New-BCBenchInvocationId
        ContainerId              = $null
        VerifiedContainerId      = $null
        ObservedContainerInvocationId = $null
        ContainerPreexisted      = $null
        ContainerSuccessfullyCreated = $false
        Company                = $null
        BcMcpUrl               = $null
        AlToolDotNetVersion    = $null
    }
    $createdEntryRoot = $false
    $createdProtectedRoot = $false
    $containerOwnershipChecked = $false
    $containerPreexisted = $false
    $ownedContainerObserved = $false
    $createdAgentIdentity = $false
    $createdAgentBcIdentity = $false
    $aclApplicationStarted = $false
    $oldGithubToken = $env:GITHUB_TOKEN
    $oldAdoToken = $env:ADO_TOKEN

    try {
        Write-BCBenchSecretMask -Secret $GithubToken
        Write-BCBenchSecretMask -Secret $AdoToken
        Write-BCBenchSecretMask -Secret (ConvertFrom-BCBenchSecureString -SecureString $EvaluatorPassword)
        if (-not [string]::IsNullOrEmpty($GithubToken)) { $env:GITHUB_TOKEN = $GithubToken }
        if (-not [string]::IsNullOrEmpty($AdoToken)) { $env:ADO_TOKEN = $AdoToken }

        New-Item -ItemType Directory -Path $entryRootPath | Out-Null
        $createdEntryRoot = $true
        New-Item -ItemType Directory -Path $protectedRootPath | Out-Null
        $createdProtectedRoot = $true
        foreach ($path in @(
            $context.AgentWorkspace,
            $context.AgentLogs,
            $context.MountedStaging,
            $context.EvaluatorWorkspaces,
            $context.Evidence,
            $context.TrustedSource,
            $context.Checkpoints,
            $context.FinalResults
        )) {
            New-Item -ItemType Directory -Path $path | Out-Null
        }
        $agentTools = Invoke-BCBenchOperation -Operations $Operations -Name StageAgentTools -Context $context -Default {
            param($operationContext)
            return New-BCBenchAgentTools `
                -EntryRoot $operationContext.EntryRoot `
                -BenchmarkRoot $operationContext.BenchmarkRoot `
                -SourceWorkerPath $operationContext.SourceWorkerPath
        }
        $context.AgentTools = Resolve-BCBenchAbsolutePath -Path ([string]$agentTools.AgentTools)
        $context.WorkerPath = Resolve-BCBenchAbsolutePath -Path ([string]$agentTools.WorkerPath)
        $context.WorkerSha256 = [string]$agentTools.WorkerSha256

        $context.Entry = Invoke-BCBenchOperation -Operations $Operations -Name ResolveEntry -Context $context -Default {
            param($operationContext)
            Import-Module (Join-Path $PSScriptRoot "DatasetEntry.psm1") -Force -DisableNameChecking
            $entries = @(Get-DatasetEntries -DatasetPath $operationContext.DatasetPath -InstanceId $operationContext.InstanceId)
            if ($entries.Count -ne 1) {
                throw "Expected exactly one dataset entry for '$($operationContext.InstanceId)', found $($entries.Count)."
            }
            return $entries[0]
        }
        $datasetVersion = [string]$context.Entry.environment_setup_version
        if (-not [string]::IsNullOrEmpty($context.Version) -and $context.Version -ne $datasetVersion) {
            throw "Requested version '$($context.Version)' does not match dataset version '$datasetVersion'."
        }
        $context.Version = $datasetVersion
        $context.AlToolDotNetVersion = if (([version]$context.Version).Major -lt 29) { "8.0" } else { "10.0" }
        $context.EvaluatorCredential = [PSCredential]::new($EvaluatorUsername, $EvaluatorPassword)

        Invoke-BCBenchOperation -Operations $Operations -Name CloneRepository -Context $context -Default {
            param($operationContext)
            Import-Module (Join-Path $PSScriptRoot "BCBenchUtils.psm1") -Force -DisableNameChecking
            $cloneInfo = Get-RepoCloneInfo -Entry $operationContext.Entry
            Invoke-GitCloneWithRetry `
                -RepoUrl $cloneInfo.Url `
                -Token $cloneInfo.Token `
                -ClonePath $operationContext.BaselineWorkspace `
                -CommitSha $operationContext.Entry.base_commit `
                -SparseCheckoutPaths $cloneInfo.SparseCheckoutPaths
        } | Out-Null

        $initialContainerState = Invoke-BCBenchOperation -Operations $Operations -Name InspectContainer -Context $context -Default {
            param($operationContext)
            return Get-BCBenchContainerState -ContainerName $operationContext.ContainerName
        }
        $containerPreexisted = [bool]$initialContainerState.Exists
        $containerOwnershipChecked = $true
        $context.ContainerPreexisted = $containerPreexisted
        if ($containerPreexisted) {
            throw "Container '$($context.ContainerName)' already exists."
        }
        $containerCreationError = $null
        try {
            Invoke-BCBenchOperation -Operations $Operations -Name CreateContainer -Context $context -Default {
                param($operationContext)
                Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
                Import-Module (Join-Path $PSScriptRoot "BCBenchUtils.psm1") -Force -DisableNameChecking
                Import-Module (Join-Path $PSScriptRoot "BCContainerManagement.psm1") -Force -DisableNameChecking
                $artifactParameters = @{ version = $operationContext.Version; Country = $operationContext.Country }
                $artifactConfig = Get-BCBenchArtifactConfig -Category $operationContext.Category
                foreach ($key in $artifactConfig.Keys) { $artifactParameters[$key] = $artifactConfig[$key] }
                $operationContext.ArtifactUrl = Get-BCArtifactUrl @artifactParameters
                [string[]]$additionalParameters = @(
                    "--label",
                    "bcbench.lifecycle.invocation=$($operationContext.ContainerInvocationId)"
                )
                foreach ($mapping in @(
                    @($operationContext.BaselineWorkspace, "C:\bcbench\baseline"),
                    @($operationContext.AgentWorkspace, "C:\bcbench\agent"),
                    @($operationContext.EvaluatorWorkspaces, "C:\bcbench\evaluators"),
                    @($operationContext.MountedStaging, "C:\bcbench\staging")
                )) {
                    $additionalParameters += "--volume"
                    $additionalParameters += "$($mapping[0]):$($mapping[1])"
                }
                New-BCContainerSync `
                    -ContainerName $operationContext.ContainerName `
                    -Version $operationContext.Version `
                    -ArtifactUrl $operationContext.ArtifactUrl `
                    -Credential $operationContext.EvaluatorCredential `
                    -AcceptInsiderEula ([bool]$artifactConfig.accept_insiderEula) `
                    -AdditionalParameters $additionalParameters
            } | Out-Null
        }
        catch {
            $containerCreationError = $_
        }
        $createdContainerState = Invoke-BCBenchOperation -Operations $Operations -Name InspectContainer -Context $context -Default {
            param($operationContext)
            return Get-BCBenchContainerState -ContainerName $operationContext.ContainerName
        }
        if ([bool]$createdContainerState.Exists) {
            $context.ContainerId = [string]$createdContainerState.Id
            $context.ObservedContainerInvocationId = [string]$createdContainerState.InvocationId
            if ([string]::IsNullOrEmpty($context.ContainerId)) {
                throw "Container '$($context.ContainerName)' was observed without a Docker ID."
            }
            if ([string]$createdContainerState.InvocationId -ne $context.ContainerInvocationId) {
                throw "Container '$($context.ContainerName)' appeared with a missing or different lifecycle invocation label."
            }
            $ownedContainerObserved = $true
        }
        if ($null -ne $containerCreationError) {
            throw $containerCreationError
        }
        if (-not $ownedContainerObserved) {
            throw "Container '$($context.ContainerName)' was not observable after creation."
        }
        $context.ContainerSuccessfullyCreated = $true

        Invoke-BCBenchOperation -Operations $Operations -Name CreateCompiler -Context $context -Default {
            param($operationContext)
            Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
            if ([string]::IsNullOrEmpty($operationContext.ArtifactUrl)) {
                throw "ArtifactUrl was not set by container creation."
            }
            New-BcCompilerFolder -artifactUrl $operationContext.ArtifactUrl -containerName $operationContext.ContainerName | Out-Null
        } | Out-Null
        Invoke-BCBenchOperation -Operations $Operations -Name InitializeContainer -Context $context -Default {
            param($operationContext)
            Import-Module (Join-Path $PSScriptRoot "BCContainerManagement.psm1") -Force -DisableNameChecking
            Initialize-ContainerForDevelopment -ContainerName $operationContext.ContainerName -RepoVersion ([version]$operationContext.Version)
        } | Out-Null
        $context.Company = Invoke-BCBenchOperation -Operations $Operations -Name GetCompany -Context $context -Default {
            param($operationContext)
            Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
            Import-Module (Join-Path $PSScriptRoot "BCContainerManagement.psm1") -Force -DisableNameChecking
            return Get-BCContainerCompany -ContainerName $operationContext.ContainerName
        }
        if ($context.BcMcp) {
            Invoke-BCBenchOperation -Operations $Operations -Name PublishMcp -Context $context -Default {
                param($operationContext)
                Import-Module (Join-Path $PSScriptRoot "BCContainerManagement.psm1") -Force -DisableNameChecking
                Publish-MCPConfigApp `
                    -ContainerName $operationContext.ContainerName `
                    -Version $operationContext.Version `
                    -Credential $operationContext.EvaluatorCredential `
                    -BuildRoot $operationContext.BaselineWorkspace
            } | Out-Null
            $mcpInfo = Invoke-BCBenchOperation -Operations $Operations -Name GetMcpInfo -Context $context -Default {
                param($operationContext)
                Import-Module (Join-Path $PSScriptRoot "BCContainerManagement.psm1") -Force -DisableNameChecking
                return Get-BCMCPConnectionInfo -ContainerName $operationContext.ContainerName
            }
            $context.BcMcpUrl = [string]$mcpInfo.BaseUrl
        }

        $context.AgentIdentity = Invoke-BCBenchOperation -Operations $Operations -Name CreateAgentIdentity -Context $context -Default {
            param($operationContext)
            return New-BCBenchAgentIdentity -InstanceId $operationContext.InstanceId
        }
        $createdAgentIdentity = $true
        $context.AclTransaction = New-BCBenchAgentAclTransaction -Identity $context.AgentIdentity
        $context.AgentBcIdentity = Invoke-BCBenchOperation -Operations $Operations -Name CreateBcIdentity -Context $context -Default {
            param($operationContext)
            return New-BCBenchAgentBcUser -InstanceId $operationContext.InstanceId -ContainerName $operationContext.ContainerName
        }
        $createdAgentBcIdentity = $true
        $aclApplicationStarted = $true
        $aclResult = Invoke-BCBenchOperation -Operations $Operations -Name ApplyAcl -Context $context -Default {
            param($operationContext)
            return Set-BCBenchWorkspaceAcl `
                -Identity $operationContext.AgentIdentity `
                -EntryRoot $operationContext.EntryRoot `
                -BaselineWorkspace $operationContext.BaselineWorkspace `
                -AgentWorkspace $operationContext.AgentWorkspace `
                -AgentLogs $operationContext.AgentLogs `
                -AgentTools $operationContext.AgentTools `
                -MountedStaging $operationContext.MountedStaging `
                -EvaluatorWorkspaces $operationContext.EvaluatorWorkspaces `
                -Evidence $operationContext.Evidence `
                -ProtectedRoot $operationContext.ProtectedRoot `
                -BenchmarkRoot $operationContext.BenchmarkRoot `
                -DatasetPath $operationContext.DatasetPath `
                -ToolRoots $operationContext.ToolRoots `
                -RuntimeExecutablePaths @($operationContext.PythonBaseExecutable) `
                -RuntimeRoots @($operationContext.PythonBasePrefix) `
                -SourceWorkerPath $operationContext.SourceWorkerPath `
                -WorkerPath $operationContext.WorkerPath `
                -WorkerSha256 $operationContext.WorkerSha256 `
                -AclTransaction $operationContext.AclTransaction
        }
        if ($null -ne $aclResult -and $null -ne $aclResult.PSObject.Properties["AclTransaction"]) {
            $context.AclTransaction = $aclResult.AclTransaction
        }

        $evaluatorPasswordText = ConvertFrom-BCBenchSecureString -SecureString $EvaluatorPassword
        Write-BCBenchSecretMask -Secret $evaluatorPasswordText
        Write-BCBenchSecretMask -Secret $context.AgentBcIdentity.Password
        $serverUrl = "http://$($context.ContainerName)"
        $serverInstance = "BC"
        $context.EvaluatorContainerConfig = [PSCustomObject][ordered]@{
            name            = $context.ContainerName
            username        = $context.EvaluatorUsername
            password        = $evaluatorPasswordText
            company         = [string]$context.Company
            server_url      = $serverUrl
            server_instance = $serverInstance
            mcp_url         = [string]$context.BcMcpUrl
        }
        $context.AgentContainerConfig = [PSCustomObject][ordered]@{
            name            = $context.ContainerName
            username        = $context.AgentBcIdentity.Username
            password        = $context.AgentBcIdentity.Password
            company         = [string]$context.Company
            server_url      = $serverUrl
            server_instance = $serverInstance
            mcp_url         = [string]$context.BcMcpUrl
        }
        $outputs = [ordered]@{
            entry_root                    = $context.EntryRoot
            baseline_workspace            = $context.BaselineWorkspace
            agent_workspace               = $context.AgentWorkspace
            agent_logs                    = $context.AgentLogs
            agent_tools                   = $context.AgentTools
            contained_process_worker      = $context.WorkerPath
            contained_process_worker_sha256 = $context.WorkerSha256
            contained_process_python      = $context.PythonBaseExecutable
            mounted_staging               = $context.MountedStaging
            evaluator_workspaces          = $context.EvaluatorWorkspaces
            evidence                      = $context.Evidence
            protected_root                = $context.ProtectedRoot
            trusted_source                = $context.TrustedSource
            checkpoints                   = $context.Checkpoints
            final_results                 = $context.FinalResults
            container_name                = $context.ContainerName
            container_invocation_id       = $context.ContainerInvocationId
            container_id                  = $context.ContainerId
            container_observed_invocation_id = $context.ObservedContainerInvocationId
            bc_version                    = $context.Version
            bc_country                    = $context.Country
            bc_server_url                 = $serverUrl
            bc_server_instance            = $serverInstance
            bc_mcp_url                    = [string]$context.BcMcpUrl
            evaluator_username            = $context.EvaluatorUsername
            evaluator_password            = $evaluatorPasswordText
            agent_os_username             = $context.AgentIdentity.Username
            agent_os_password             = $context.AgentIdentity.Password
            agent_os_domain               = $context.AgentIdentity.Domain
            agent_bc_username             = $context.AgentBcIdentity.Username
            agent_bc_password             = $context.AgentBcIdentity.Password
            bc_company                    = [string]$context.Company
            evaluator_container_config    = ($context.EvaluatorContainerConfig | ConvertTo-Json -Compress)
            agent_container_config        = ($context.AgentContainerConfig | ConvertTo-Json -Compress)
            al_tool_dotnet_version         = $context.AlToolDotNetVersion
            al_mcp                         = ([bool]$context.AlMcp).ToString().ToLowerInvariant()
            bc_mcp                         = ([bool]$context.BcMcp).ToString().ToLowerInvariant()
        }
        foreach ($item in $outputs.GetEnumerator()) {
            Add-BCBenchOutput -Path $GithubOutput -Name $item.Key -Value ([string]$item.Value)
        }
        $environment = [ordered]@{
            BCBENCH_ENTRY_ROOT             = $context.EntryRoot
            BCBENCH_BASELINE_WORKSPACE     = $context.BaselineWorkspace
            BCBENCH_AGENT_WORKSPACE        = $context.AgentWorkspace
            BCBENCH_AGENT_LOGS             = $context.AgentLogs
            BCBENCH_AGENT_TOOLS            = $context.AgentTools
            BCBENCH_CONTAINED_PROCESS_WORKER = $context.WorkerPath
            BCBENCH_CONTAINED_PROCESS_WORKER_SHA256 = $context.WorkerSha256
            BCBENCH_CONTAINED_PROCESS_PYTHON = $context.PythonBaseExecutable
            BCBENCH_MOUNTED_STAGING        = $context.MountedStaging
            BCBENCH_EVALUATOR_WORKSPACES   = $context.EvaluatorWorkspaces
            BCBENCH_EVIDENCE               = $context.Evidence
            BCBENCH_PROTECTED_ROOT         = $context.ProtectedRoot
            BCBENCH_TRUSTED_SOURCE         = $context.TrustedSource
            BCBENCH_CHECKPOINTS            = $context.Checkpoints
            BCBENCH_FINAL_RESULTS          = $context.FinalResults
            BCBENCH_AGENT_OS_USERNAME      = $context.AgentIdentity.Username
            BCBENCH_AGENT_OS_PASSWORD      = $context.AgentIdentity.Password
            BCBENCH_AGENT_OS_DOMAIN        = $context.AgentIdentity.Domain
            BCBENCH_AGENT_BC_USERNAME      = $context.AgentBcIdentity.Username
            BCBENCH_AGENT_BC_PASSWORD      = $context.AgentBcIdentity.Password
            BC_CONTAINER_NAME              = $context.ContainerName
            BCBENCH_CONTAINER_INVOCATION_ID = $context.ContainerInvocationId
            BCBENCH_CONTAINER_ID            = $context.ContainerId
            BC_SERVER_URL                  = $serverUrl
            BC_SERVER_INSTANCE             = $serverInstance
            BC_SERVER_USERNAME             = $context.EvaluatorUsername
            BC_SERVER_PASSWORD             = $evaluatorPasswordText
            BC_COMPANY                     = [string]$context.Company
            BC_MCP_URL                     = [string]$context.BcMcpUrl
            AL_TOOL_DOTNET_VERSION         = $context.AlToolDotNetVersion
            BCBENCH_AL_MCP                 = ([bool]$context.AlMcp).ToString().ToLowerInvariant()
            BCBENCH_BC_MCP                 = ([bool]$context.BcMcp).ToString().ToLowerInvariant()
        }
        foreach ($item in $environment.GetEnumerator()) {
            Add-BCBenchOutput -Path $GithubEnv -Name $item.Key -Value ([string]$item.Value)
        }
        return $context
    }
    catch {
        $originalError = $_
        [System.Collections.Generic.List[string]]$cleanupErrors = [System.Collections.Generic.List[string]]::new()
        $containerAbsenceVerified = $false
        $containerOwnershipVerified = $false
        $preserveRestrictedEvidence = $false
        $localIdentityRequirementMet = -not $createdAgentIdentity

        if (
            $containerOwnershipChecked -and
            -not $containerPreexisted -and
            -not [string]::IsNullOrEmpty([string]$context.ContainerId) -and
            -not [string]::IsNullOrEmpty([string]$context.ContainerInvocationId)
        ) {
            try {
                Get-BCBenchVerifiedContainerId -Operations $Operations -Context $context | Out-Null
                $containerOwnershipVerified = $true
            }
            catch {
                $cleanupErrors.Add("container ownership verification: $($_.Exception.Message)")
                $preserveRestrictedEvidence = $true
            }
        }
        else {
            try {
                Assert-BCBenchContainerAbsent -Operations $Operations -Context $context
                $containerAbsenceVerified = $true
            }
            catch {
                $cleanupErrors.Add("container absence verification: $($_.Exception.Message)")
                $preserveRestrictedEvidence = $true
            }
        }

        if ($containerOwnershipVerified) {
            $bcUserAbsenceVerified = -not $createdAgentBcIdentity
            if ($createdAgentBcIdentity) {
                try {
                    Invoke-BCBenchOperation -Operations $Operations -Name RemoveBcIdentity -Context $context -Default {
                        param($operationContext)
                        Remove-BCBenchAgentBcUser `
                            -ContainerName $operationContext.ContainerName `
                            -Username $operationContext.AgentBcIdentity.Username `
                            -ExpectedContainerId $operationContext.ContainerId `
                            -ExpectedInvocationId $operationContext.ContainerInvocationId `
                            -Operations $Operations
                    } | Out-Null
                }
                catch {
                    $cleanupErrors.Add("BC user removal: $($_.Exception.Message)")
                    $preserveRestrictedEvidence = $true
                }
                if (-not $preserveRestrictedEvidence) {
                    try {
                        Invoke-BCBenchOperation -Operations $Operations -Name VerifyBcIdentityAbsent -Context $context -Default {
                            param($operationContext)
                            $verifiedContainerId = Get-BCBenchVerifiedContainerId -Operations $Operations -Context $operationContext
                            Assert-BCBenchAgentBcUserAbsent `
                                -ContainerId $verifiedContainerId `
                                -Username $operationContext.AgentBcIdentity.Username
                        } | Out-Null
                        $bcUserAbsenceVerified = $true
                    }
                    catch {
                        $cleanupErrors.Add("BC user absence verification: $($_.Exception.Message)")
                        $preserveRestrictedEvidence = $true
                    }
                }
            }
            if ($bcUserAbsenceVerified) {
                try {
                    Invoke-BCBenchOperation -Operations $Operations -Name RemoveContainer -Context $context -Default {
                        param($operationContext)
                        $output = & docker container rm --force $operationContext.VerifiedContainerId 2>&1
                        if ($LASTEXITCODE -ne 0) {
                            throw "Docker removal failed for owned container ID '$($operationContext.VerifiedContainerId)': $(@($output) -join [Environment]::NewLine)"
                        }
                    } | Out-Null
                }
                catch {
                    $cleanupErrors.Add("container removal: $($_.Exception.Message)")
                    $preserveRestrictedEvidence = $true
                }
                if (-not $preserveRestrictedEvidence) {
                    try {
                        Assert-BCBenchContainerAbsent -Operations $Operations -Context $context
                        $containerAbsenceVerified = $true
                    }
                    catch {
                        $cleanupErrors.Add("post-removal container verification: $($_.Exception.Message)")
                        $preserveRestrictedEvidence = $true
                    }
                }
            }
        }

        $aclCleanupSucceeded = -not $aclApplicationStarted
        if ($containerAbsenceVerified) {
            if ($aclApplicationStarted) {
                try {
                    Invoke-BCBenchOperation -Operations $Operations -Name RemoveAcl -Context $context -Default {
                        param($operationContext)
                        Remove-BCBenchAgentAcl -Transaction $operationContext.AclTransaction
                    } | Out-Null
                    $context.AclTransaction.CleanupComplete = $true
                    $aclCleanupSucceeded = $true
                }
                catch {
                    $cleanupErrors.Add("ACL cleanup: $($_.Exception.Message)")
                    $preserveRestrictedEvidence = $true
                }
            }
            if ($createdAgentIdentity -and $aclCleanupSucceeded) {
                try {
                    Invoke-BCBenchOperation -Operations $Operations -Name RemoveAgentIdentity -Context $context -Default {
                        param($operationContext)
                        Remove-BCBenchAgentIdentity -Username $operationContext.AgentIdentity.Username
                    } | Out-Null
                    $localIdentityRequirementMet = $true
                }
                catch {
                    $cleanupErrors.Add("local user removal: $($_.Exception.Message)")
                    try {
                        Invoke-BCBenchOperation -Operations $Operations -Name DisableAgentIdentity -Context $context -Default {
                            param($operationContext)
                            Disable-BCBenchAgentIdentity -Username $operationContext.AgentIdentity.Username
                        } | Out-Null
                        Invoke-BCBenchOperation -Operations $Operations -Name VerifyAgentIdentityDisabled -Context $context -Default {
                            param($operationContext)
                            Assert-BCBenchAgentIdentityDisabled -Username $operationContext.AgentIdentity.Username
                        } | Out-Null
                        $localIdentityRequirementMet = $true
                    }
                    catch {
                        $cleanupErrors.Add("local user disablement/verification: $($_.Exception.Message)")
                        $preserveRestrictedEvidence = $true
                    }
                }
            }
            if ($aclCleanupSucceeded -and $localIdentityRequirementMet) {
                if ($createdEntryRoot) {
                    try { Remove-BCBenchCreatedRoot -Path $entryRootPath }
                    catch { $cleanupErrors.Add("entry root removal: $($_.Exception.Message)") }
                }
                if ($createdProtectedRoot) {
                    try { Remove-BCBenchCreatedRoot -Path $protectedRootPath }
                    catch { $cleanupErrors.Add("protected root removal: $($_.Exception.Message)") }
                }
            }
        }

        if ($createdAgentIdentity -and (-not $containerAbsenceVerified -or -not $aclCleanupSucceeded)) {
            try {
                Invoke-BCBenchOperation -Operations $Operations -Name DisableAgentIdentity -Context $context -Default {
                    param($operationContext)
                    Disable-BCBenchAgentIdentity -Username $operationContext.AgentIdentity.Username
                } | Out-Null
                Invoke-BCBenchOperation -Operations $Operations -Name VerifyAgentIdentityDisabled -Context $context -Default {
                    param($operationContext)
                    Assert-BCBenchAgentIdentityDisabled -Username $operationContext.AgentIdentity.Username
                } | Out-Null
                $localIdentityRequirementMet = $true
            }
            catch {
                $cleanupErrors.Add("local user disablement/verification: $($_.Exception.Message)")
                $preserveRestrictedEvidence = $true
            }
            $cleanupErrors.Add(
                "restricted identity, SID ACLs, EntryRoot, and ProtectedRoot retained for quarantine because safe cleanup was not verified: $($context.AgentIdentity.Username)"
            )
        }

        $quarantinePath = $null
        if ($cleanupErrors.Count -gt 0) {
            try {
                $quarantinePath = Write-BCBenchCleanupQuarantine `
                    -Context $context `
                    -OriginalError $originalError.Exception.Message `
                    -CleanupErrors @($cleanupErrors)
            }
            catch {
                $cleanupErrors.Add("quarantine marker persistence: $($_.Exception.Message)")
                $quarantinePath = Get-BCBenchQuarantinePath -ProtectedRoot $context.ProtectedRoot
            }
        }
        $cleanupMessage = if ($cleanupErrors.Count -gt 0) {
            " Cleanup errors: $($cleanupErrors -join '; '). Quarantine marker: $quarantinePath"
        }
        else {
            ""
        }
        throw "Bug-fix lifecycle setup failed: $($originalError.Exception.Message).$cleanupMessage"
    }
    finally {
        $env:GITHUB_TOKEN = $oldGithubToken
        $env:ADO_TOKEN = $oldAdoToken
    }
}

Export-ModuleMember -Function `
    Get-BCBenchContainerState, `
    New-BCBenchAgentTools, `
    New-BCBenchAgentIdentity, `
    Remove-BCBenchAgentAcl, `
    Remove-BCBenchAgentIdentity, `
    Assert-BCBenchReadExecuteRoots, `
    Resolve-BCBenchPythonRuntime, `
    Set-BCBenchWorkspaceAcl, `
    Test-BCBenchIdentityAccess, `
    New-BCBenchAgentBcUser, `
    Remove-BCBenchAgentBcUser, `
    Invoke-BCBenchBugFixLifecycle
