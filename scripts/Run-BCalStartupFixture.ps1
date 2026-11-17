param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$Package,
    [Parameter(Mandatory)][string]$Archive,
    [Parameter(Mandatory)][string]$SymbolCache,
    [Parameter(Mandatory)][string]$Work,
    [Parameter(Mandatory)][string]$Output
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'Machine-wide temporary denial is permitted only on the dedicated GitHub-hosted Windows runner.'
}
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator firewall control is required.' }
$group = "BCal-Startup-ZeroProvider-$env:GITHUB_RUN_ID"
if (@(Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue).Count) { throw 'A prior fixture denial exists; do not rerun.' }
$ranges = @('0.0.0.0-126.255.255.255', '128.0.0.0-255.255.255.255', '::', '::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')
$proofPath = Join-Path $env:RUNNER_TEMP 'startup-network-denial.json'
$proof = [ordered]@{ status = 'not-admitted'; allPrograms = $false; allProtocols = $false; ipv4NonLoopbackDenied = $false; ipv6NonLoopbackDenied = $false; profilesEnabled = $false; externalTcpProbeBlocked = $false; loopbackTcpProbeAllowed = $false; rulesVerified = 0 }
$stage = 'firewall_profiles'
try {
    $profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore)
    if ($profiles.Count -ne 3 -or @($profiles | Where-Object { -not $_.Enabled }).Count) { throw 'All active firewall profiles must be enabled.' }
    $proof.profilesEnabled = $true
    $stage = 'firewall_rules'
    New-NetFirewallRule -Name "$group-v4" -DisplayName "$group-v4" -Group $group -Direction Outbound -Action Block -Enabled True -Profile Any -Protocol Any -Program Any -RemoteAddress $ranges[0..1] | Out-Null
    New-NetFirewallRule -Name "$group-v6" -DisplayName "$group-v6" -Group $group -Direction Outbound -Action Block -Enabled True -Profile Any -Protocol Any -Program Any -RemoteAddress $ranges[2..3] | Out-Null
    $rules = @(Get-NetFirewallRule -PolicyStore ActiveStore -Group $group)
    if ($rules.Count -ne 2) { throw 'Both outbound denial rules must be active.' }
    foreach ($rule in $rules) {
        $application = $rule | Get-NetFirewallApplicationFilter
        $port = $rule | Get-NetFirewallPortFilter
        $address = $rule | Get-NetFirewallAddressFilter
        $expected = if ($rule.Name.EndsWith('-v4')) { $ranges[0..1] } else { $ranges[2..3] }
        if ($rule.Direction -ne 'Outbound' -or $rule.Action -ne 'Block' -or $rule.Enabled -ne 'True' -or
            $application.Program -ne 'Any' -or $port.Protocol -ne 'Any' -or
            @(Compare-Object @($address.RemoteAddress | ForEach-Object { if ($_ -eq '::/128') { '::' } else { $_ } }) $expected).Count) { throw 'Active outbound denial differs.' }
        $proof.rulesVerified++
    }
    $stage = 'external_tcp_probe'
    $probe = [Net.Sockets.TcpClient]::new()
    try {
        $pending = $probe.ConnectAsync('1.1.1.1', 443)
        try { $connected = $pending.Wait(3000) -and $probe.Connected } catch [AggregateException] { $connected = $false }
        if ($connected) { throw 'External TCP probe unexpectedly connected; no fixture admitted.' }
        $proof.externalTcpProbeBlocked = $true
    } finally { $probe.Dispose() }
    $stage = 'loopback_tcp_probe'
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $local = [Net.Sockets.TcpClient]::new()
    try {
        $pending = $local.ConnectAsync('127.0.0.1', $listener.LocalEndpoint.Port)
        if (-not $pending.Wait(3000) -or -not $local.Connected) { throw 'Loopback control unavailable.' }
        $accepted = $listener.AcceptTcpClient()
        $accepted.Dispose()
        $proof.loopbackTcpProbeAllowed = $true
    } finally { $local.Dispose(); $listener.Stop() }
    $proof.allPrograms = $true
    $proof.allProtocols = $true
    $proof.ipv4NonLoopbackDenied = $true
    $proof.ipv6NonLoopbackDenied = $true
    $proof.status = 'outbound-denial-active'
    $proof | ConvertTo-Json | Set-Content -LiteralPath $proofPath
    $stage = 'offline_fixture'
    & $Python scripts\bcal_startup_fixture.py --package $Package --archive $Archive --symbol-cache $SymbolCache --work $Work --output $Output --network-proof $proofPath
    if ($LASTEXITCODE -ne 0) { throw 'Offline startup fixture failed; no replacement authorized.' }
} finally {
    if ($proof.status -ne 'outbound-denial-active') {
        $proof.status = 'network-admission-failed'
        $proof.failureStage = $stage
        $proof | ConvertTo-Json | Set-Content -LiteralPath $proofPath
    }
    Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    $removed = @(Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue).Count -eq 0
    @{ denialRulesRemoved = $removed; providerCredentialsFetched = $false } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $env:RUNNER_TEMP 'startup-network-cleanup.json')
    if (-not $removed) { throw 'Temporary firewall cleanup failed.' }
}
