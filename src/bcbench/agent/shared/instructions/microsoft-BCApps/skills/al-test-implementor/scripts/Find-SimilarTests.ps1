# Find-SimilarTests.ps1
# v0 retrieval: extract keywords from a SUT (system-under-test) AL file, rank
# rows in the AL test corpus by keyword hits in `body`, and return top-N as JSON.
#
# Filters:
#   * kind = "test" (always)
#   * exclude any row whose bodyHash is in eval/split.json's `holdout`
#   * optional -Subject and -Interaction
#
# See openspec/changes/improve-al-test-implementor-skill/specs/al-test-implementor-skill/spec.md
# (Requirement: Example retrieval mechanism).

[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $SutPath,
    [string] $CorpusPath,
    [string] $SplitPath,
    [string] $IdfPath,
    [int]    $TopN = 3,
    [switch] $NoIdf,
    [string] $PrTitle,
    [switch] $NoPathKeywords,
    [ValidateSet('posting','pages','reports','xml-integration','calculation','setup','permissions','other')]
    [string] $Subject,
    [ValidateSet('direct-call','confirm-dialog','modal-page','report-request','notification','asserterror','none')]
    [string] $Interaction
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Resolve inputs
# ---------------------------------------------------------------------------

if (-not (Test-Path -LiteralPath $SutPath)) {
    throw "SUT not found: $SutPath"
}

# Default paths point to the bundled corpus shipped with the skill
# (../data/, sibling to scripts/). These can be overridden for testing.
$dataDir = (Resolve-Path (Join-Path $PSScriptRoot '..\data')).Path
if (-not $CorpusPath) { $CorpusPath = Join-Path $dataDir 'corpus-deduped.jsonl' }
if (-not $SplitPath)  { $SplitPath  = Join-Path $dataDir 'split.json' }
if (-not $IdfPath)    { $IdfPath    = Join-Path $dataDir 'keyword-idf.json' }

if (-not (Test-Path -LiteralPath $CorpusPath)) {
    throw "Bundled corpus not found at $CorpusPath. The skill is incomplete; reinstall it."
}

# ---------------------------------------------------------------------------
# Load holdout set (skip silently if not present — useful in a fresh setup)
# ---------------------------------------------------------------------------

$holdout = New-Object 'System.Collections.Generic.HashSet[string]'
if (Test-Path -LiteralPath $SplitPath) {
    $split = Get-Content -Raw -LiteralPath $SplitPath | ConvertFrom-Json -Depth 5
    foreach ($h in $split.holdout) { [void] $holdout.Add([string]$h) }
}

# ---------------------------------------------------------------------------
# Load IDF index (D15). When -NoIdf is set or the index is absent, fall back
# to uniform keyword weighting (Round 1 behaviour).
# ---------------------------------------------------------------------------

$useIdf = -not $NoIdf.IsPresent -and (Test-Path -LiteralPath $IdfPath)
$idfDf       = $null
$idfTotal    = 0
$idfDefault  = 0.0
if ($useIdf) {
    $idf = Get-Content -Raw -LiteralPath $IdfPath | ConvertFrom-Json -Depth 5
    $idfTotal = [int]$idf.totalDocs
    $idfDf    = @{}
    foreach ($p in $idf.df.PSObject.Properties) {
        $idfDf[$p.Name] = [int]$p.Value
    }
    # IDF for an unseen token: treat as df=1 (very rare = high weight, but capped
    # by log(N/1)).
    $idfDefault = [math]::Log([double]$idfTotal / 1.0)
}

function Get-Idf {
    [OutputType([double])]
    param([string]$Token)
    if (-not $useIdf) { return 1.0 }
    if ($idfDf.ContainsKey($Token)) {
        return [math]::Log([double]$idfTotal / [double]$idfDf[$Token])
    }
    return $idfDefault
}

# ---------------------------------------------------------------------------
# Extract keywords from the SUT
# ---------------------------------------------------------------------------
# Keywords harvested:
#   * Record "..." names                    (table types)
#   * page "..." / Page "..." names         (UI surfaces)
#   * report "..." names                    (reports)
#   * codeunit "..." names                  (target codeunits)
#   * procedure / local procedure names     (entry points likely under test)
#   * object name from object header line   (e.g. codeunit 50100 "My Helper")

$sutText = Get-Content -Raw -LiteralPath $SutPath
$keywords = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
# Track which keywords came from the path/title rather than the body so we can
# boost them at scoring time — path/title tokens are strong domain signals.
$pathKeywords = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)

function _Add-Keyword {
    param([string]$kw, [switch]$FromPath)
    if (-not $kw) { return }
    $kw = $kw.Trim()
    if ($kw.Length -lt 3) { return }
    [void] $script:keywords.Add($kw)
    if ($FromPath.IsPresent) { [void] $script:pathKeywords.Add($kw) }
}

# Record/page/report/codeunit type references.
foreach ($m in [regex]::Matches($sutText, '(?i)\b(Record|page|report|codeunit|xmlport|enum|interface)\s+"([^"]{2,})"')) {
    _Add-Keyword $m.Groups[2].Value
}
# Quoted object names anywhere (e.g., DATABASE::"Customer" or page header).
foreach ($m in [regex]::Matches($sutText, '"([A-Za-z][^"]{2,80})"')) {
    _Add-Keyword $m.Groups[1].Value
}
# Procedure names declared in the SUT.
foreach ($m in [regex]::Matches($sutText, '(?im)^\s*(?:local\s+|internal\s+)?procedure\s+([A-Za-z_][A-Za-z0-9_]*)')) {
    _Add-Keyword $m.Groups[1].Value
}
# Object header (e.g. `codeunit 50100 "My Posting Helper"`).
foreach ($m in [regex]::Matches($sutText, '(?im)^\s*(?:codeunit|page|report|table|xmlport|query|enum|interface)\s+\d+\s+"?([A-Za-z][A-Za-z0-9_ \-\.\,&]{2,})"?')) {
    _Add-Keyword $m.Groups[1].Value
}

# ---------------------------------------------------------------------------
# Path-segment and PR-title keywords (Round 3 augmentation).
#
# Many BC SUTs are thin event subscribers / parsing helpers whose *body* lacks
# domain vocabulary (e.g. SwissQRBillPurchases.Codeunit.al barely says "QR").
# But the path almost always carries the domain (`Apps/CH/SwissQRBill/...`,
# `Apps/DK/NemhandelNotification/...`), and the PR title says it explicitly.
# We split CamelCase/PascalCase segments into individual tokens and into the
# original camel-cased form so both `SwissQRBill` and `Swiss`/`QR`/`Bill`
# can match test bodies.
# ---------------------------------------------------------------------------

function _Split-Camel {
    param([string]$Text)
    if (-not $Text) { return @() }
    $out = New-Object 'System.Collections.Generic.List[string]'
    # Split on non-letter/digit boundaries first.
    foreach ($chunk in ($Text -split '[^A-Za-z0-9]+' | Where-Object { $_ })) {
        $out.Add($chunk) | Out-Null
        # Then split CamelCase: insert space between lower→Upper and Letter→Digit.
        $spaced = [regex]::Replace($chunk, '([a-z0-9])([A-Z])', '$1 $2')
        $spaced = [regex]::Replace($spaced, '([A-Z])([A-Z][a-z])', '$1 $2')
        foreach ($w in ($spaced -split '\s+')) {
            if ($w -and $w.Length -ge 3) { $out.Add($w) | Out-Null }
        }
    }
    return ,$out
}

if (-not $NoPathKeywords.IsPresent) {
    $pathInfo = [System.IO.FileInfo]::new((Resolve-Path $SutPath).Path)
    # Strip everything up to and including the first 'App' / 'Apps' / 'src'
    # segment so we keep only domain-meaningful path tokens. Works for any
    # repo layout (BC-Bench staging, navagent, BCApps, customer extensions).
    $rel = $pathInfo.FullName -replace '\\','/'
    $m = [regex]::Match($rel, '(?i)/(?:App|Apps|src|source)/(.+)$')
    if ($m.Success) { $rel = $m.Groups[1].Value }
    # Skipped path tokens that carry no domain signal.
    $pathStop = @('App','app','Apps','Layers','src','source','test','Tests','BaseApp','Codeunits','Codeunit','codeunits','codeunit','W1','APAC','EMEA','NA','DACH')
    $segs = $rel -split '/'
    if ($segs.Count -gt 0) {
        # Drop the filename itself — its object name is already harvested.
        $segs = $segs[0..([Math]::Max(0, $segs.Count - 2))]
    }
    foreach ($seg in $segs) {
        if (-not $seg) { continue }
        if ($pathStop -contains $seg) { continue }
        foreach ($t in (_Split-Camel $seg)) { _Add-Keyword $t -FromPath }
    }
}

if ($PrTitle) {
    foreach ($t in (_Split-Camel $PrTitle)) { _Add-Keyword $t -FromPath }
    # Also add quoted phrases from the title.
    foreach ($m in [regex]::Matches($PrTitle, '"([^"]{3,})"')) { _Add-Keyword $m.Groups[1].Value -FromPath }
}

if ($keywords.Count -eq 0) {
    throw "No keywords extracted from $SutPath. Is this an AL file?"
}

# ---------------------------------------------------------------------------
# Score corpus rows
# ---------------------------------------------------------------------------

$kwArray = @($keywords)
# Per-keyword IDF weight (1.0 when -NoIdf). Path-derived keywords get a 2x
# boost on top of their IDF — they are strong, intentional domain signals.
$pathBoost = 2.0
$kwWeights = New-Object 'double[]' $kwArray.Count
for ($i = 0; $i -lt $kwArray.Count; $i++) {
    $w = Get-Idf -Token $kwArray[$i]
    if ($pathKeywords.Contains($kwArray[$i])) { $w = $w * $pathBoost }
    $kwWeights[$i] = $w
}
# Pre-build per-keyword regex (case-insensitive, word-ish boundary on each side).
$kwRegex = $kwArray | ForEach-Object {
    [regex]::new('(?i)' + [regex]::Escape($_), 'Compiled')
}

$ranked = New-Object 'System.Collections.Generic.List[object]'

$reader = [System.IO.StreamReader]::new($CorpusPath)
try {
    while (-not $reader.EndOfStream) {
        $line = $reader.ReadLine()
        if (-not $line -or -not $line.Trim()) { continue }

        $row = $line | ConvertFrom-Json -Depth 100

        if ($row.kind -ne 'test') { continue }
        if ($holdout.Contains([string]$row.bodyHash)) { continue }
        if ($Subject     -and $row.subject     -ne $Subject)     { continue }
        if ($Interaction -and $row.interaction -ne $Interaction) { continue }

        $body = [string]$row.body
        if (-not $body) { continue }

        $score    = 0.0
        $rawHits  = 0
        $matched  = New-Object 'System.Collections.Generic.List[string]'
        for ($i = 0; $i -lt $kwRegex.Count; $i++) {
            $hits = $kwRegex[$i].Matches($body).Count
            if ($hits -gt 0) {
                # Binary (presence) IDF scoring: each matched keyword contributes
                # its IDF weight once, regardless of TF. This avoids common-but-
                # not-rare tokens (Sales Header, Sales Line) dominating the score
                # when they happen to be repeated many times in unrelated tests.
                $score   += $kwWeights[$i]
                $rawHits += $hits
                $matched.Add($kwArray[$i]) | Out-Null
            }
        }
        if ($rawHits -le 0) { continue }

        $ranked.Add([pscustomobject]@{
            score           = [math]::Round($score, 3)
            rawHits         = $rawHits
            uniqueKeywords  = $matched.Count
            matchedKeywords = @($matched)
            row             = $row
        }) | Out-Null
    }
}
finally {
    $reader.Dispose()
}

# Rank by score (IDF-weighted when enabled) desc, then uniqueKeywords desc,
# then shorter loc preferred.
$top = @($ranked |
    Sort-Object -Property `
        @{ Expression = 'score';          Descending = $true }, `
        @{ Expression = 'uniqueKeywords'; Descending = $true }, `
        @{ Expression = { [int]$_.row.loc } } |
    Select-Object -First $TopN)

# ---------------------------------------------------------------------------
# Emit JSON
# ---------------------------------------------------------------------------

$result = [ordered]@{
    sutPath            = (Resolve-Path $SutPath).Path
    keywordsExtracted  = $kwArray.Count
    candidatesScored   = $ranked.Count
    holdoutExcluded    = $holdout.Count
    idfEnabled         = $useIdf
    idfTotalDocs       = $idfTotal
    filters            = [ordered]@{ subject = $Subject; interaction = $Interaction }
    results            = @($top | ForEach-Object {
        [ordered]@{
            score           = $_.score
            rawHits         = $_.rawHits
            uniqueKeywords  = $_.uniqueKeywords
            matchedKeywords = $_.matchedKeywords
            kind            = $_.row.kind
            subject         = $_.row.subject
            interaction     = $_.row.interaction
            name            = $_.row.name
            file            = $_.row.file
            commitId        = $_.row.commitId
            pr              = $_.row.pr
            loc             = $_.row.loc
            bodyHash        = $_.row.bodyHash
            callsLibraries  = @($_.row.callsLibraries)
            asserts         = @($_.row.asserts)
            body            = $_.row.body
        }
    })
}

$result | ConvertTo-Json -Depth 10
