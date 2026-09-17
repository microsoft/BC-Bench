Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:BcContainerHelperVersion = [version]"6.1.18"
$script:UsersGroupSid = "S-1-5-32-545"
$script:AdministratorsGroupSid = "S-1-5-32-544"
$script:SystemSid = "S-1-5-18"

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

function New-BCBenchAgentIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$InstanceId,
        [ValidateRange(1, 50)][int]$MaxCollisionRetries = 10
    )

    for ($attempt = 1; $attempt -le $MaxCollisionRetries; $attempt++) {
        $username = New-BCBenchScopedUsername -Prefix bcb -InstanceId $InstanceId
        if ($null -ne (Get-LocalUser -Name $username -ErrorAction SilentlyContinue)) {
            continue
        }

        $password = New-BCBenchPassword
        $securePassword = ConvertTo-SecureString $password -AsPlainText -Force
        $createdUser = $false
        try {
            New-LocalUser `
                -Name $username `
                -Password $securePassword `
                -Description "BC-Bench restricted agent for $InstanceId" `
                -AccountNeverExpires `
                -PasswordNeverExpires | Out-Null
            $createdUser = $true
            Add-LocalGroupMember -SID $script:UsersGroupSid -Member $username
            Assert-BCBenchAgentNotPrivileged -Username $username
        }
        catch {
            if ($createdUser) {
                Remove-LocalUser -Name $username -ErrorAction SilentlyContinue
            }
            throw
        }

        Write-BCBenchSecretMask -Secret $password
        return [PSCustomObject]@{
            Username = $username
            Password = $password
            Domain   = [Environment]::MachineName
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
    if ($null -ne (Get-LocalUser -Name $Username -ErrorAction SilentlyContinue)) {
        Remove-LocalUser -Name $Username -ErrorAction Stop
    }
}

function Resolve-BCBenchAbsolutePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [IO.Path]::GetFullPath($Path).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
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
        $matchingRule = @($acl.Access | Where-Object {
            $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
            (Test-BCBenchAclIdentity -Actual $_.IdentityReference -Expected ([string]$expectedRule.Identity)) -and
            ($_.FileSystemRights -band $expectedRights) -eq $expectedRights
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
        [Parameter(Mandatory = $true)][string]$ProtectedRoot,
        [string]$PythonExecutable = (Get-Command python -ErrorAction Stop).Source,
        [string]$ContainedProcessScriptPath = (Join-Path $PSScriptRoot "Invoke-ContainedProcess.ps1"),
        [string]$ContainedProcessWorkerPath = (Join-Path (Split-Path $PSScriptRoot -Parent) "src\bcbench\agent\shared\contained_process_worker.py")
    )

    $probeId = [guid]::NewGuid().ToString("N")
    $workspaceProbe = Join-Path $AgentWorkspace "identity-access-$probeId.txt"
    $protectedProbe = Join-Path $ProtectedRoot "identity-access-$probeId.txt"
    [IO.File]::WriteAllText($protectedProbe, "evaluator-only", [Text.UTF8Encoding]::new($false))
    $probeRoot = Join-Path $ProtectedRoot ".identity-access-$probeId"
    New-Item -ItemType Directory -Path $probeRoot | Out-Null

    $probeScript = @'
$ErrorActionPreference = "Stop"
$workspaceWriteSucceeded = $false
$protectedReadDenied = $false
$protectedWriteDenied = $false
$dockerCliDenied = $false
$dockerPipeDenied = $false
$protectedReadError = $null
$protectedWriteError = $null
$dockerCliError = $null
$dockerPipeError = $null
try {
    [IO.File]::WriteAllText($env:BCBENCH_WORKSPACE_PROBE, "agent-write")
    $workspaceWriteSucceeded = $true
}
catch {
    $workspaceWriteError = $_.Exception.Message
}
try {
    [void][IO.File]::ReadAllText($env:BCBENCH_PROTECTED_PROBE)
}
catch {
    $protectedReadDenied = $true
    $protectedReadError = $_.Exception.Message
}
try {
    [IO.File]::WriteAllText($env:BCBENCH_PROTECTED_WRITE_PROBE, "forbidden")
}
catch {
    $protectedWriteDenied = $true
    $protectedWriteError = $_.Exception.Message
}
try {
    $dockerOutput = & docker version 2>&1 | Out-String
    $dockerCliDenied = $LASTEXITCODE -ne 0
    if ($dockerCliDenied) { $dockerCliError = $dockerOutput.Trim() }
}
catch {
    $dockerCliDenied = $true
    $dockerCliError = $_.Exception.Message
}
try {
    $pipe = [IO.Pipes.NamedPipeClientStream]::new(".", "docker_engine", [IO.Pipes.PipeDirection]::InOut)
    try {
        $pipe.Connect(1500)
        $dockerPipeDenied = -not $pipe.IsConnected
        if (-not $dockerPipeDenied) { $dockerPipeError = "Connection unexpectedly succeeded" }
    }
    finally {
        $pipe.Dispose()
    }
}
catch {
    $dockerPipeDenied = $true
    $dockerPipeError = $_.Exception.Message
}
[PSCustomObject]@{
    WorkspaceWriteSucceeded = $workspaceWriteSucceeded
    WorkspaceWriteError = $workspaceWriteError
    ProtectedReadDenied = $protectedReadDenied
    ProtectedReadError = $protectedReadError
    ProtectedWriteDenied = $protectedWriteDenied
    ProtectedWriteError = $protectedWriteError
    DockerCliDenied = $dockerCliDenied
    DockerCliError = $dockerCliError
    DockerPipeDenied = $dockerPipeDenied
    DockerPipeError = $dockerPipeError
    ProcessId = $PID
    WorkspaceProbePath = $env:BCBENCH_WORKSPACE_PROBE
    ProtectedProbePath = $env:BCBENCH_PROTECTED_PROBE
} | ConvertTo-Json -Compress
'@
    $encodedProbe = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($probeScript))
    $powershellExecutable = (Get-Process -Id $PID).Path
    $requestPath = Join-Path $probeRoot "request.json"
    $sharedPath = Join-Path $probeRoot "shared"
    New-Item -ItemType Directory -Path $sharedPath | Out-Null
    $workerRequestPath = Join-Path $sharedPath "worker-request.json"
    $gatePath = Join-Path $sharedPath "launch.gate"
    $stdoutPath = Join-Path $sharedPath "stdout.txt"
    $stderrPath = Join-Path $sharedPath "stderr.txt"
    $request = @{
        command         = @($powershellExecutable, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", $encodedProbe)
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
            BCBENCH_PROTECTED_WRITE_PROBE   = (Join-Path $ProtectedRoot "forbidden-$probeId.txt")
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
            -WorkerStartupTimeoutSeconds 30
        if ($LASTEXITCODE -ne 0) {
            throw "Contained identity probe failed with wrapper exit code $LASTEXITCODE."
        }
        $wrapperResult = ($wrapperOutput | Out-String).Trim() | ConvertFrom-Json
        if ($wrapperResult.timed_out -or $wrapperResult.returncode -ne 0) {
            throw "Contained identity probe child failed: $($wrapperResult.stderr)"
        }
        return ([string]$wrapperResult.stdout).Trim() | ConvertFrom-Json
    }
    finally {
        Remove-Item -LiteralPath $protectedProbe -Force -ErrorAction SilentlyContinue
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
        [Parameter(Mandatory = $true)][string]$MountedStaging,
        [Parameter(Mandatory = $true)][string]$EvaluatorWorkspaces,
        [Parameter(Mandatory = $true)][string]$Evidence,
        [Parameter(Mandatory = $true)][string]$ProtectedRoot,
        [Parameter(Mandatory = $true)][string[]]$ToolRoots,
        [string[]]$WorkerRequestPaths = @(),
        [string[]]$WorkerOutputPaths = @(),
        [Parameter(DontShow = $true)][scriptblock]$IcaclsRunner,
        [Parameter(DontShow = $true)][scriptblock]$AclVerifier,
        [Parameter(DontShow = $true)][scriptblock]$AccessValidator
    )

    $entryPaths = @{
        BaselineWorkspace   = $BaselineWorkspace
        AgentWorkspace      = $AgentWorkspace
        AgentLogs           = $AgentLogs
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
    foreach ($toolRoot in $ToolRoots | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $toolRoot -PathType Container)) {
            throw "Tool root does not exist: $toolRoot"
        }
        foreach ($managedRoot in @($EntryRoot, $ProtectedRoot)) {
            if ((Test-BCBenchPathContains -Ancestor $managedRoot -Path $toolRoot) -or (Test-BCBenchPathContains -Ancestor $toolRoot -Path $managedRoot)) {
                throw "Tool root '$toolRoot' must not overlap lifecycle storage '$managedRoot'."
            }
        }
    }
    foreach ($workerPath in @($WorkerRequestPaths) + @($WorkerOutputPaths)) {
        if (-not (Test-Path -LiteralPath $workerPath -PathType Leaf)) {
            throw "Worker access path must be an existing file: $workerPath"
        }
        if ((Resolve-BCBenchAbsolutePath -Path $workerPath).Equals(
            (Resolve-BCBenchAbsolutePath -Path $MountedStaging),
            [StringComparison]::OrdinalIgnoreCase
        ) -or -not (Test-BCBenchPathContains -Ancestor $MountedStaging -Path $workerPath)) {
            throw "Worker access path must be a strict descendant of MountedStaging: $workerPath"
        }
        Assert-BCBenchNoReparseComponents -Path $workerPath
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

    Set-BCBenchExplicitAcl `
        -Path $EntryRoot `
        -Rules ($baseRules + $agentTraverse) `
        -AgentAccount $agentAccount `
        -IcaclsRunner $IcaclsRunner `
        -AclVerifier $AclVerifier
    foreach ($privatePath in @($BaselineWorkspace, $MountedStaging, $EvaluatorWorkspaces, $Evidence, $ProtectedRoot)) {
        Set-BCBenchExplicitAcl `
            -Path $privatePath `
            -Rules $baseRules `
            -AgentAccount $agentAccount `
            -RemoveAgent `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
    }
    Set-BCBenchExplicitAcl `
        -Path $AgentWorkspace `
        -Rules ($baseRules + $agentModify) `
        -AgentAccount $agentAccount `
        -IcaclsRunner $IcaclsRunner `
        -AclVerifier $AclVerifier
    Set-BCBenchExplicitAcl `
        -Path $AgentLogs `
        -Rules ($baseRules + $agentModify) `
        -AgentAccount $agentAccount `
        -IcaclsRunner $IcaclsRunner `
        -AclVerifier $AclVerifier
    foreach ($toolRoot in $ToolRoots | Select-Object -Unique) {
        $agentRead = [PSCustomObject]@{ Identity = $agentAccount; Rights = "ReadAndExecute" }
        Set-BCBenchExplicitAcl `
            -Path $toolRoot `
            -Rules @($agentRead) `
            -AgentAccount $agentAccount `
            -PreserveInheritance `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
    }
    if ($WorkerRequestPaths.Count -gt 0 -or $WorkerOutputPaths.Count -gt 0) {
        Set-BCBenchExplicitAcl `
            -Path $MountedStaging `
            -Rules ($baseRules + $agentTraverse) `
            -AgentAccount $agentAccount `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
    }
    foreach ($requestPath in $WorkerRequestPaths) {
        $agentRead = [PSCustomObject]@{ Identity = $agentAccount; Rights = "ReadAndExecute" }
        Set-BCBenchExplicitAcl `
            -Path $requestPath `
            -Rules ($baseRules + $agentRead) `
            -AgentAccount $agentAccount `
            -IsFile `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
    }
    foreach ($outputPath in $WorkerOutputPaths) {
        Set-BCBenchExplicitAcl `
            -Path $outputPath `
            -Rules ($baseRules + $agentModify) `
            -AgentAccount $agentAccount `
            -IsFile `
            -IcaclsRunner $IcaclsRunner `
            -AclVerifier $AclVerifier
    }

    $validationParameters = @{
        Identity        = $Identity
        AgentWorkspace  = $AgentWorkspace
        AgentLogs       = $AgentLogs
        ProtectedRoot   = $ProtectedRoot
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
        "DockerCliDenied",
        "DockerPipeDenied"
    )) {
        if (-not [bool]$result.$property) {
            throw "Restricted identity access verification failed: $property was false."
        }
    }
    return $result
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

function Remove-BCBenchAgentBcUser {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ContainerName,
        [Parameter(Mandatory = $true)][string]$Username,
        [Parameter(Mandatory = $true)][string]$Password
    )

    if ($Username -notmatch "^bca-[a-f0-9]{7}-[a-f0-9]{6}$") {
        throw "Refusing to remove unexpected BC username '$Username'."
    }
    Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
    Invoke-ScriptInBcContainer -containerName $ContainerName -ScriptBlock {
        param([string]$Username)

        $serverInstance = (Get-NAVServerInstance | Select-Object -First 1).ServerInstance
        $existingUser = Get-NAVServerUser -ServerInstance $serverInstance -Tenant "default" -UserName $Username
        if ($null -eq $existingUser) {
            return
        }
        Remove-NAVServerUser -ServerInstance $serverInstance -Tenant "default" -UserName $Username -Force
        if ($null -ne (Get-NAVServerUser -ServerInstance $serverInstance -Tenant "default" -UserName $Username)) {
            throw "BC user '$Username' still exists after removal."
        }
    } -ArgumentList $Username
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
    $entryPaths = @{
        BaselineWorkspace   = Join-Path $entryRootPath "baseline-workspace"
        AgentWorkspace      = Join-Path $entryRootPath "agent-workspace"
        AgentLogs           = Join-Path $entryRootPath "agent-logs"
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
        BaselineWorkspace      = $entryPaths.BaselineWorkspace
        AgentWorkspace         = $entryPaths.AgentWorkspace
        AgentLogs              = $entryPaths.AgentLogs
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
        EvaluatorContainerConfig = $null
        AgentContainerConfig     = $null
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
    $successfullyCreatedContainer = $false
    $createdAgentIdentity = $false
    $createdAgentBcIdentity = $false
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

        $containerPreexisted = [bool](Invoke-BCBenchOperation -Operations $Operations -Name TestContainerExists -Context $context -Default {
            param($operationContext)
            Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
            Import-Module (Join-Path $PSScriptRoot "BCContainerManagement.psm1") -Force -DisableNameChecking
            return Test-ContainerExists -ContainerName $operationContext.ContainerName
        })
        $containerOwnershipChecked = $true
        $context.ContainerPreexisted = $containerPreexisted
        if ($containerPreexisted) {
            throw "Container '$($context.ContainerName)' already exists."
        }
        Invoke-BCBenchOperation -Operations $Operations -Name CreateContainer -Context $context -Default {
            param($operationContext)
            Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
            Import-Module (Join-Path $PSScriptRoot "BCBenchUtils.psm1") -Force -DisableNameChecking
            Import-Module (Join-Path $PSScriptRoot "BCContainerManagement.psm1") -Force -DisableNameChecking
            $artifactParameters = @{ version = $operationContext.Version; Country = $operationContext.Country }
            $artifactConfig = Get-BCBenchArtifactConfig -Category $operationContext.Category
            foreach ($key in $artifactConfig.Keys) { $artifactParameters[$key] = $artifactConfig[$key] }
            $operationContext.ArtifactUrl = Get-BCArtifactUrl @artifactParameters
            [string[]]$additionalParameters = @()
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
        $successfullyCreatedContainer = $true
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
        $context.AgentBcIdentity = Invoke-BCBenchOperation -Operations $Operations -Name CreateBcIdentity -Context $context -Default {
            param($operationContext)
            return New-BCBenchAgentBcUser -InstanceId $operationContext.InstanceId -ContainerName $operationContext.ContainerName
        }
        $createdAgentBcIdentity = $true
        Invoke-BCBenchOperation -Operations $Operations -Name ApplyAcl -Context $context -Default {
            param($operationContext)
            return Set-BCBenchWorkspaceAcl `
                -Identity $operationContext.AgentIdentity `
                -EntryRoot $operationContext.EntryRoot `
                -BaselineWorkspace $operationContext.BaselineWorkspace `
                -AgentWorkspace $operationContext.AgentWorkspace `
                -AgentLogs $operationContext.AgentLogs `
                -MountedStaging $operationContext.MountedStaging `
                -EvaluatorWorkspaces $operationContext.EvaluatorWorkspaces `
                -Evidence $operationContext.Evidence `
                -ProtectedRoot $operationContext.ProtectedRoot `
                -ToolRoots $operationContext.ToolRoots
        } | Out-Null

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
            mounted_staging               = $context.MountedStaging
            evaluator_workspaces          = $context.EvaluatorWorkspaces
            evidence                      = $context.Evidence
            protected_root                = $context.ProtectedRoot
            trusted_source                = $context.TrustedSource
            checkpoints                   = $context.Checkpoints
            final_results                 = $context.FinalResults
            container_name                = $context.ContainerName
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
        if ($createdAgentBcIdentity) {
            try {
                Invoke-BCBenchOperation -Operations $Operations -Name RemoveBcIdentity -Context $context -Default {
                    param($operationContext)
                    Remove-BCBenchAgentBcUser `
                        -ContainerName $operationContext.ContainerName `
                        -Username $operationContext.AgentBcIdentity.Username `
                        -Password $operationContext.AgentBcIdentity.Password
                } | Out-Null
            }
            catch { $cleanupErrors.Add("BC user: $($_.Exception.Message)") }
        }
        if ($createdAgentIdentity) {
            try {
                Invoke-BCBenchOperation -Operations $Operations -Name RemoveAgentIdentity -Context $context -Default {
                    param($operationContext)
                    Remove-BCBenchAgentIdentity -Username $operationContext.AgentIdentity.Username
                } | Out-Null
            }
            catch { $cleanupErrors.Add("local user: $($_.Exception.Message)") }
        }
        $removeOwnedContainer = $successfullyCreatedContainer
        if ($containerOwnershipChecked -and -not $containerPreexisted -and -not $removeOwnedContainer) {
            try {
                $removeOwnedContainer = [bool](Invoke-BCBenchOperation -Operations $Operations -Name TestContainerExists -Context $context -Default {
                    param($operationContext)
                    Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
                    Import-Module (Join-Path $PSScriptRoot "BCContainerManagement.psm1") -Force -DisableNameChecking
                    return Test-ContainerExists -ContainerName $operationContext.ContainerName
                })
            }
            catch { $cleanupErrors.Add("container ownership check: $($_.Exception.Message)") }
        }
        if ($containerOwnershipChecked -and -not $containerPreexisted -and $removeOwnedContainer) {
            try {
                Invoke-BCBenchOperation -Operations $Operations -Name RemoveContainer -Context $context -Default {
                    param($operationContext)
                    Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking
                    Import-Module (Join-Path $PSScriptRoot "BCContainerManagement.psm1") -Force -DisableNameChecking
                    if (Test-ContainerExists -ContainerName $operationContext.ContainerName) {
                        Remove-BcContainer -containerName $operationContext.ContainerName
                    }
                } | Out-Null
            }
            catch { $cleanupErrors.Add("container: $($_.Exception.Message)") }
        }
        if ($createdProtectedRoot) {
            try { Remove-BCBenchCreatedRoot -Path $protectedRootPath }
            catch { $cleanupErrors.Add("protected root: $($_.Exception.Message)") }
        }
        if ($createdEntryRoot) {
            try { Remove-BCBenchCreatedRoot -Path $entryRootPath }
            catch { $cleanupErrors.Add("entry root: $($_.Exception.Message)") }
        }
        $cleanupMessage = if ($cleanupErrors.Count -gt 0) {
            " Cleanup errors: $($cleanupErrors -join '; ')"
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
    New-BCBenchAgentIdentity, `
    Remove-BCBenchAgentIdentity, `
    Set-BCBenchWorkspaceAcl, `
    Test-BCBenchIdentityAccess, `
    New-BCBenchAgentBcUser, `
    Remove-BCBenchAgentBcUser, `
    Invoke-BCBenchBugFixLifecycle
