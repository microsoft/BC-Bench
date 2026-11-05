param(
    [Parameter(Mandatory = $true)]
    [string] $CaseRun,

    [Parameter(Mandatory = $true)]
    [string] $AggregateRun,

    [Parameter(Mandatory = $true)]
    [string] $Entry
)

$ErrorActionPreference = "Stop"
$resultPath = Join-Path $CaseRun "$Entry.jsonl"
if (-not (Test-Path -LiteralPath $resultPath)) {
    throw "BCal evaluation did not produce $resultPath."
}

New-Item -ItemType Directory -Force -Path $AggregateRun | Out-Null
Get-ChildItem -Path $CaseRun -Recurse -File | ForEach-Object {
    $relativePath = [IO.Path]::GetRelativePath($CaseRun, $_.FullName)
    $destination = Join-Path $AggregateRun $relativePath
    if (Test-Path -LiteralPath $destination) {
        throw "BCal experiment output collision at $destination."
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $destination
}
