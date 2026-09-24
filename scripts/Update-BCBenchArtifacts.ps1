using module .\BCBenchUtils.psm1

param(
    [Parameter(Mandatory = $true)]
    [string]$CandidatesJson,

    [string]$ConfigPath = (Join-Path $PSScriptRoot '..' 'config' 'bc-artifacts.json')
)

$ErrorActionPreference = 'Stop'
$candidates = $CandidatesJson | ConvertFrom-Json -AsHashtable
if ($candidates -isnot [hashtable] -or $candidates.Count -eq 0) {
    throw 'Expected a nonempty BC artifact candidate map.'
}

$artifacts = Get-Content $ConfigPath -Raw | ConvertFrom-Json -AsHashtable
$updates = @{}
foreach ($version in $candidates.Keys) {
    if ($candidates[$version] -isnot [string] -or [string]::IsNullOrWhiteSpace($candidates[$version])) {
        throw "Expected a BC artifact URL for version $version."
    }
    $updates[$version] = Get-BCBenchArtifactUrl -Version $version -CandidateUrl $candidates[$version]
}

if (-not ($updates.Keys | Where-Object { $artifacts.bcartifacts[$_] -ne $updates[$_] })) { return }
foreach ($version in $updates.Keys) {
    $artifacts.bcartifacts[$version] = $updates[$version]
}
($artifacts | ConvertTo-Json -Depth 5) + "`n" | Set-Content $ConfigPath -NoNewline
