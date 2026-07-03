# Scan-LibraryDocs.ps1
#
# *** MAINTENANCE-ONLY ***
#
# This script regenerates the bundled `references/library-api.md` from BC's
# `Library*.Codeunit.al` source. It needs the BC source tree on disk and is
# only run by the skill author when the underlying Library API surface
# changes. **The skill itself never invokes it at task time.** Agents read
# the pre-generated `references/library-api.md` directly.
#
# Inputs:
#   -RootPath  Path to a BC source tree to scan recursively for
#              `Library*.Codeunit.al` files. No default — must be supplied
#              by the maintainer.
#   -OutPath   Output Markdown file (default: bundled
#              `references/library-api.md`).
#   -Force     Bypass mtime cache and regenerate unconditionally.
#
# mtime cache: if -OutPath exists and its LastWriteTime is newer than every
# scanned source AL file, the script exits without rewriting.

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $RootPath,
    [string] $OutPath   = (Join-Path $PSScriptRoot '..\references\library-api.md'),
    [switch] $Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $RootPath)) {
    throw "RootPath not found: $RootPath"
}

# ---------------------------------------------------------------------------
# Discover Library*.Codeunit.al
# ---------------------------------------------------------------------------

Write-Host "Scanning for Library*.Codeunit.al under $RootPath ..." -ForegroundColor Cyan
$libFiles = @(Get-ChildItem -Path $RootPath -Recurse -Filter 'Library*.Codeunit.al' -File -ErrorAction SilentlyContinue)
Write-Host ("  found {0} library codeunit(s)" -f $libFiles.Count)

if ($libFiles.Count -eq 0) {
    throw "No Library*.Codeunit.al files found under $RootPath."
}

# ---------------------------------------------------------------------------
# mtime cache check
# ---------------------------------------------------------------------------

if (-not $Force.IsPresent -and (Test-Path -LiteralPath $OutPath)) {
    $outMtime = (Get-Item -LiteralPath $OutPath).LastWriteTimeUtc
    $newestSrc = ($libFiles | Measure-Object -Property LastWriteTimeUtc -Maximum).Maximum
    if ($newestSrc -le $outMtime) {
        Write-Host "Up to date — output mtime $outMtime is newer than all sources. Use -Force to override." -ForegroundColor Green
        return
    }
}

# ---------------------------------------------------------------------------
# Parse one .al file -> list of [pscustomobject]@{ name, params, summary,
# remarks, paramDocs[], hasDocs }
# ---------------------------------------------------------------------------

$reHeader = [regex]::new('(?im)^\s*codeunit\s+\d+\s+"?([A-Za-z][A-Za-z0-9_ \-\.\,&]{2,})"?', 'Compiled')
$reProc   = [regex]::new('(?im)^\s*(?:local\s+|internal\s+)?procedure\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((?<params>[^)]*)\)', 'Compiled')

function Get-FileSummary {
    param([string]$Text)
    # File-level summary: any `/// <summary>...</summary>` that appears before
    # the first `codeunit` keyword.
    $idx = $Text.IndexOf("`ncodeunit ", [System.StringComparison]::OrdinalIgnoreCase)
    if ($idx -lt 0) { $idx = $Text.IndexOf("codeunit ", [System.StringComparison]::OrdinalIgnoreCase) }
    if ($idx -lt 0) { return $null }
    $head = $Text.Substring(0, $idx)
    $m = [regex]::Match($head, '(?is)<summary>\s*(.*?)\s*</summary>')
    if ($m.Success) { return ($m.Groups[1].Value -replace '\s*///\s*', ' ').Trim() }
    return $null
}

function Parse-LibraryFile {
    param([string]$Path)

    $text = Get-Content -Raw -LiteralPath $Path
    $hdr  = $reHeader.Match($text)
    if (-not $hdr.Success) { return $null }

    $friendly = $hdr.Groups[1].Value.Trim()
    # Normalize "Library - Sales" -> "LibrarySales".
    $normalized = ($friendly -replace '[^A-Za-z0-9]', '')

    $fileSummary = Get-FileSummary -Text $text

    $lines = $text -split "`r?`n"
    $procedures = New-Object 'System.Collections.Generic.List[object]'

    for ($i = 0; $i -lt $lines.Count; $i++) {
        $m = $reProc.Match($lines[$i])
        if (-not $m.Success) { continue }

        $name   = $m.Groups[1].Value
        $params = $m.Groups['params'].Value.Trim()

        # Walk up to collect contiguous /// lines.
        $docLines = New-Object 'System.Collections.Generic.List[string]'
        $j = $i - 1
        while ($j -ge 0) {
            $t = $lines[$j].Trim()
            if ($t.StartsWith('///')) {
                $docLines.Insert(0, $t.Substring(3).TrimStart())
            } elseif ($t -eq '' -or $t -match '^\s*\[\w' -or $t -match '^\s*//') {
                # Skip attribute lines, blank lines, plain // comments.
                $j--; continue
            } else {
                break
            }
            $j--
        }

        $docBlock = ($docLines -join "`n")
        $summary  = ''
        $remarks  = ''
        $paramDocs = New-Object 'System.Collections.Generic.List[object]'

        $sm = [regex]::Match($docBlock, '(?is)<summary>\s*(.*?)\s*</summary>')
        if ($sm.Success) { $summary = ($sm.Groups[1].Value -replace '\s+', ' ').Trim() }
        $rm = [regex]::Match($docBlock, '(?is)<remarks>\s*(.*?)\s*</remarks>')
        if ($rm.Success) { $remarks = ($rm.Groups[1].Value -replace '\s+', ' ').Trim() }
        foreach ($pm in [regex]::Matches($docBlock, '(?is)<param\s+name="([^"]+)"\s*>\s*(.*?)\s*</param>')) {
            $paramDocs.Add([pscustomobject]@{
                name = $pm.Groups[1].Value
                desc = ($pm.Groups[2].Value -replace '\s+', ' ').Trim()
            }) | Out-Null
        }

        # PowerShell strict-mode quirk: `[object[]]@($emptyList)` throws
        # "Argument types do not match". Build the array branchlessly instead.
        if ($paramDocs.Count -gt 0) {
            $pdArr = $paramDocs.ToArray()
        } else {
            $pdArr = New-Object 'object[]' 0
        }
        $procedures.Add([pscustomobject]@{
            name      = $name
            params    = $params
            summary   = [string]$summary
            remarks   = [string]$remarks
            paramDocs = $pdArr
            hasDocs   = [bool]([string]$summary)
        }) | Out-Null
    }

    return [pscustomobject]@{
        path        = $Path
        friendly    = $friendly
        normalized  = $normalized
        fileSummary = $fileSummary
        procedures  = $procedures
    }
}

$libraries = New-Object 'System.Collections.Generic.List[object]'
foreach ($f in $libFiles) {
    try {
        $parsed = Parse-LibraryFile -Path $f.FullName
    } catch {
        Write-Host ("  ! parse failed: {0} -- {1}" -f $f.FullName, $_.Exception.Message) -ForegroundColor Yellow
        continue
    }
    if ($parsed -and $parsed.procedures.Count -gt 0) {
        $libraries.Add($parsed) | Out-Null
    }
}

Write-Host ("  parsed {0} libraries with at least 1 procedure" -f $libraries.Count)

# ---------------------------------------------------------------------------
# Dedupe layer mirrors (e.g. LibrarySales exists in W1, APAC, country test
# folders). Group by normalized name; for each group keep the variant with the
# most documented procedures, then the longest procedure list, then the
# shortest path. Other variants are dropped \u2014 their content is identical or a
# subset of the kept one for the purpose of this index.
# ---------------------------------------------------------------------------

$beforeDedup = $libraries.Count
$librariesDeduped = New-Object 'System.Collections.Generic.List[object]'
$grouped = $libraries | Group-Object -Property normalized
foreach ($g in $grouped) {
    $bestScore = -1
    $best = $null
    foreach ($cand in $g.Group) {
        $docCount = 0
        foreach ($p in $cand.procedures) { if ($p.hasDocs) { $docCount++ } }
        $score = ($docCount * 100000) + $cand.procedures.Count
        if ($score -gt $bestScore -or ($score -eq $bestScore -and $cand.path.Length -lt $best.path.Length)) {
            $bestScore = $score
            $best = $cand
        }
    }
    if ($best) { $librariesDeduped.Add($best) | Out-Null }
}
$libraries = $librariesDeduped
Write-Host ("  deduped layer mirrors: {0} -> {1}" -f $beforeDedup, $libraries.Count)

# ---------------------------------------------------------------------------
# Sort: libraries alphabetically; procedures within each library alphabetically.
# ---------------------------------------------------------------------------

$librariesSorted = @($libraries | Sort-Object -Property 'friendly')

# ---------------------------------------------------------------------------
# Emit Markdown
# ---------------------------------------------------------------------------

$sb = New-Object System.Text.StringBuilder

[void]$sb.AppendLine('# AL test library API reference')
[void]$sb.AppendLine()
[void]$sb.AppendLine('Auto-generated by `~/.copilot/skills/al-test-implementor/scripts/Scan-LibraryDocs.ps1`. Do not hand-edit; instead, add or improve XML doc comments (`/// <summary>`, `/// <remarks>`, `/// <param>`) on the source AL `procedure` declarations and re-run the scanner.')
[void]$sb.AppendLine()
[void]$sb.AppendLine(('Generated: `{0}`' -f (Get-Date).ToString('o')))
[void]$sb.AppendLine(('Source root: `{0}`' -f $RootPath))
[void]$sb.AppendLine()

# Counts
$totalProcs    = ($librariesSorted | ForEach-Object { $_.procedures.Count } | Measure-Object -Sum).Sum
$documentedProcs = ($librariesSorted | ForEach-Object { $_.procedures | Where-Object { $_.hasDocs } } | Measure-Object).Count
$undocumentedProcs = $totalProcs - $documentedProcs
$coveragePct = if ($totalProcs -gt 0) { [math]::Round(100.0 * $documentedProcs / $totalProcs, 1) } else { 0 }

[void]$sb.AppendLine(('- Libraries scanned: **{0}**' -f $librariesSorted.Count))
[void]$sb.AppendLine(('- Total procedures: **{0}**' -f $totalProcs))
[void]$sb.AppendLine(('- Documented (has `<summary>`): **{0}** ({1}%)' -f $documentedProcs, $coveragePct))
[void]$sb.AppendLine(('- Missing documentation: **{0}**' -f $undocumentedProcs))
[void]$sb.AppendLine()

# Per-library sections.
[void]$sb.AppendLine('## Libraries (alphabetical)')
[void]$sb.AppendLine()

foreach ($lib in $librariesSorted) {
    [void]$sb.AppendLine(('### `{0}`' -f $lib.friendly))
    [void]$sb.AppendLine()
    if ($lib.fileSummary) {
        [void]$sb.AppendLine($lib.fileSummary)
        [void]$sb.AppendLine()
    }
    $relPath = $lib.path
    if ($relPath.StartsWith($RootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        $relPath = $relPath.Substring($RootPath.Length).TrimStart('\','/')
    }
    [void]$sb.AppendLine(('Source: `{0}`' -f $relPath))
    [void]$sb.AppendLine()

    # Sort procedures alphabetically.
    $procsSorted = @($lib.procedures | Sort-Object -Property 'name')

    $documented   = @($procsSorted | Where-Object { $_.hasDocs })
    $undocumented = @($procsSorted | Where-Object { -not $_.hasDocs })

    if ($documented.Count -gt 0) {
        foreach ($p in $documented) {
            [void]$sb.AppendLine(('#### `{0}`' -f $p.name))
            [void]$sb.AppendLine()
            [void]$sb.AppendLine(('Signature: `{0}({1})`' -f $p.name, $p.params))
            [void]$sb.AppendLine()
            if ($p.summary) {
                [void]$sb.AppendLine($p.summary)
                [void]$sb.AppendLine()
            }
            if ($p.remarks) {
                [void]$sb.AppendLine('**Remarks:** ' + $p.remarks)
                [void]$sb.AppendLine()
            }
            if ($p.paramDocs.Count -gt 0) {
                [void]$sb.AppendLine('**Parameters:**')
                [void]$sb.AppendLine()
                foreach ($pd in $p.paramDocs) {
                    [void]$sb.AppendLine(('- `{0}` -- {1}' -f $pd.name, $pd.desc))
                }
                [void]$sb.AppendLine()
            }
        }
    }

    if ($undocumented.Count -gt 0) {
        [void]$sb.AppendLine(('**Missing documentation ({0} procedure(s)):**' -f $undocumented.Count))
        [void]$sb.AppendLine()
        foreach ($p in $undocumented) {
            [void]$sb.AppendLine(('- `{0}({1})`' -f $p.name, $p.params))
        }
        [void]$sb.AppendLine()
    }
}

# Ensure target directory exists.
$outDir = Split-Path -Parent $OutPath
if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
}

$sb.ToString() | Set-Content -LiteralPath $OutPath -Encoding UTF8

Write-Host ('Wrote {0}' -f $OutPath) -ForegroundColor Green
Write-Host ('  libraries:    {0}' -f $librariesSorted.Count)
Write-Host ('  procedures:   {0}' -f $totalProcs)
Write-Host ('  documented:   {0} ({1}%)' -f $documentedProcs, $coveragePct)
Write-Host ('  missing docs: {0}' -f $undocumentedProcs)
