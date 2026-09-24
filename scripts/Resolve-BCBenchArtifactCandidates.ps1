using module .\BCBenchUtils.psm1

param(
    [Parameter(Mandatory = $true)]
    [string]$EntriesJson
)

$ErrorActionPreference = 'Stop'
Import-Module BcContainerHelper -Force -DisableNameChecking

$candidates = @{}
foreach ($instanceId in ($EntriesJson | ConvertFrom-Json)) {
    $version = Get-BCBenchEntryVersion -InstanceId $instanceId -Category 'bug-fix'
    if ($candidates.ContainsKey($version)) { continue }

    $url = Get-BCArtifactUrl -version $version -country 'w1' -select 'Latest'
    if (-not $url) { throw "No upstream BC artifact found for version $version" }
    $candidates[$version] = Get-BCBenchArtifactUrl -Version $version -CandidateUrl $url
    Write-Host "Candidate for BC $version`: $url"
}

if ($candidates.Count -eq 0) { throw 'No BC artifact candidates resolved.' }
"artifacts=$($candidates | ConvertTo-Json -Compress)" | Out-File -FilePath $env:GITHUB_OUTPUT -Append
