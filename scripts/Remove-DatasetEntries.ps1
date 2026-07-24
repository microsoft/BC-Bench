<#
.SYNOPSIS
Remove dataset entries by instance-id from the JSONL dataset and problem statements.

.DESCRIPTION
Drops every line of the JSONL dataset whose instance_id is in -InstanceId, and
deletes the matching dataset/problemstatement/<instance_id> directory. Missing
files or directories are ignored (idempotent).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DatasetFile,
    [Parameter(Mandatory)][string]$ProblemStatementDir,
    [string[]]$InstanceId = @()
)

$ErrorActionPreference = 'Stop'

$ids = @($InstanceId | Where-Object { $_ -and $_.Trim() })
if ($ids.Count -eq 0) { return }

$remove = [System.Collections.Generic.HashSet[string]]::new()
foreach ($id in $ids) { [void]$remove.Add([string]$id) }

if (Test-Path $DatasetFile) {
    $kept = foreach ($line in [System.IO.File]::ReadAllLines($DatasetFile)) {
        if (-not $line.Trim()) { continue }
        $id = [string]($line | ConvertFrom-Json).instance_id
        if (-not $remove.Contains($id)) { $line }
    }
    Set-Content -Path $DatasetFile -Value $kept -Encoding utf8
}

foreach ($id in $ids) {
    $dir = Join-Path $ProblemStatementDir ([string]$id)
    if (Test-Path $dir) { Remove-Item -Recurse -Force -Path $dir }
}
