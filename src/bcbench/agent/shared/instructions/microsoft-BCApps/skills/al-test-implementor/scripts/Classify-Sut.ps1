# Classify-Sut.ps1
# Classifies a system-under-test (SUT) AL file into (subject, interaction)
# labels using the same heuristic rules the corpus classifier applies.
#
# Used by STEP 4 of the al-test-implementor skill (sub-step 4b) to pick the
# right retrieval bucket and example tests.
#
# Usage:
#   pwsh -NoProfile -File Classify-Sut.ps1 -Path <repo-relative-or-absolute-path>
#
# Output: a single-line JSON object: {"subject":"<label>","interaction":"<label>"}

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $Path,

    [string] $ClassifierModule = (Join-Path $PSScriptRoot 'AlClassifier.psm1')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ClassifierModule)) {
    throw "AlClassifier.psm1 not found at $ClassifierModule. The skill is incomplete; reinstall it."
}

Import-Module $ClassifierModule -Force

if (-not (Test-Path -LiteralPath $Path)) {
    throw "SUT file not found: $Path"
}

$body = Get-Content -LiteralPath $Path -Raw

# Normalize backslashes to forward slashes so the corpus classifier's
# path-based rules (e.g. '/posting/' or '/reports/') match Windows paths
# the skill receives at runtime.
$normalizedPath = ($Path -replace '\\','/')

# Best-effort attribute extraction: collect all [...] tokens that appear
# above procedure declarations. We don't need to parse perfectly; the
# classifier only looks for handler markers like ConfirmHandler etc., which
# are unlikely to appear in production code anyway. This keeps Classify-Sut.ps1
# behaviour aligned with the corpus classifier (which has access to per-
# procedure attribute lists).
$attrs = [regex]::Matches($body, '\[(?<a>[A-Za-z][A-Za-z0-9_]*)(?:\([^)]*\))?\]') |
    ForEach-Object { $_.Groups['a'].Value } |
    Sort-Object -Unique

# Use the relative path when the SUT lives under a repo we can detect; the
# classifier's path rules look for substrings like "/Posting/" or
# "/Reports/" so an absolute path works too.
$cls = Get-AlClassification -Path $normalizedPath -Body $body -Attributes $attrs

$result = [ordered]@{
    subject     = $cls.subject
    interaction = $cls.interaction
}

$result | ConvertTo-Json -Compress
