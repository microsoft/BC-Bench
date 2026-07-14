# Dataset Refresh: Validate-then-Prune Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `collect-and-screen` job wait for `dataset-validation` to finish, keep only the entries that passed in the draft PR's diff, and document the failed/incomplete ones in the PR description (or, if none pass, in the run summary).

**Architecture:** Builds on the existing draft-PR feature (already merged on branch `feature/dataset-refresh-draft-pr`). Three changes: (1) `New-DatasetPrBody.ps1` renders two sections (Included/Excluded) using each entry's validation `conclusion`; (2) new `scripts/Remove-DatasetEntries.ps1` prunes failed entries from the dataset by instance-id; (3) `collect-and-screen.yml` waits for the validation run, prunes the branch, then either opens/updates the draft PR (≥1 passed) or summarizes failures and deletes the branch (0 passed).

**Tech Stack:** PowerShell 7 (`pwsh`), GitHub Actions, GitHub CLI (`gh`).

## Global Constraints

- "Passed" strictly = validation matrix job `conclusion == 'success'`. Any other conclusion, an unresolved job, or a job still unfinished at the wait budget = **not passed**.
- Wait budget ~5h (300 × 60s polls); the collect job's `timeout-minutes` must exceed the budget but stay under the 6h platform cap.
- Passed entries are in the PR diff **and** the ✅ Included section. Not-passed entries are **removed from the diff** and listed in the ❌ Excluded section (PR body) or the run summary (0-passed case).
- `jobs.json` schema is now `[{ name, html_url, conclusion }]`.
- Dataset JSONL key is `instance_id`. Problem statements live in `dataset/problemstatement/<instance_id>/`.
- PR stays **draft**, base `main`, idempotent per ISO-week branch `dataset/week-XX`. PR-creation step keeps `GH_TOKEN: ${{ secrets.DATASET_PR_TOKEN || secrets.GITHUB_TOKEN }}`.
- Do NOT introduce a new test framework (no Pester) — verify pwsh via direct fixture invocation.
- Commit trailer on every commit: `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`.

---

## File Structure

- `scripts/New-DatasetPrBody.ps1` (modify) — two-section body driven by `conclusion`.
- `scripts/Remove-DatasetEntries.ps1` (create) — prune JSONL lines + problemstatement dirs by instance-id.
- `.github/workflows/collect-and-screen.yml` (modify) — wait for validation; prune step; PR-vs-summary branching; job `timeout-minutes`.

---

### Task 1: Two-section PR body in `New-DatasetPrBody.ps1`

**Files:**
- Modify: `scripts/New-DatasetPrBody.ps1` (full rewrite of the body-building logic)

**Interfaces:**
- Consumes: `-CollectedFile` (JSON array of `{ Id, Pr, Url }`); optional `-JobsFile` (JSON array of `{ name, html_url, conclusion }`); `-RunUrl` fallback; `-Repo`, `-Week`.
- Produces: markdown to stdout with a `## ✅ Included (passed validation)` section (entries whose job `conclusion == 'success'`) and, when any are not-passed, a `## ❌ Excluded (failed / incomplete validation — documented, not included)` section (with each entry's conclusion). Consumed by the workflow.

- [ ] **Step 1: Replace the script body**

Replace the entire contents of `scripts/New-DatasetPrBody.ps1` with:

```powershell
<#
.SYNOPSIS
Build the markdown body for the dataset-refresh draft PR.

.DESCRIPTION
Splits collected entries into those that passed dataset-validation (job
conclusion 'success') and those that did not, rendering an Included section
(in the PR diff) and, when any failed, an Excluded section (documented only).
An entry with no resolvable job is treated as not-passed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$CollectedFile,
    [string]$JobsFile,
    [string]$RunUrl,
    [Parameter(Mandatory)][string]$Repo,
    [Parameter(Mandatory)][string]$Week
)

$ErrorActionPreference = 'Stop'

$entries = @()
if (Test-Path $CollectedFile) {
    $entries = @(Get-Content -Raw -Path $CollectedFile | ConvertFrom-Json)
}

$jobMap = @{}
if ($JobsFile -and (Test-Path $JobsFile)) {
    foreach ($job in @(Get-Content -Raw -Path $JobsFile | ConvertFrom-Json)) {
        if ($job.name) { $jobMap[[string]$job.name] = $job }
    }
}

function Format-EntryLine {
    param($Entry, [switch]$WithConclusion)
    $job = $jobMap[[string]$Entry.Id]
    $url = if ($job -and $job.html_url) { [string]$job.html_url } elseif ($RunUrl) { $RunUrl } else { $null }
    $validation = if ($url) { " — 🔬 [validation]($url)" } else { '' }
    $line = "- ``$($Entry.Id)`` ([PR #$($Entry.Pr)]($($Entry.Url)))$validation"
    if ($WithConclusion) {
        $conclusion = if ($job -and $job.conclusion) { [string]$job.conclusion } else { 'incomplete' }
        $line += " — **$conclusion**"
    }
    $line
}

$passed = @($entries | Where-Object { $j = $jobMap[[string]$_.Id]; $j -and $j.conclusion -eq 'success' })
$failed = @($entries | Where-Object { $j = $jobMap[[string]$_.Id]; -not ($j -and $j.conclusion -eq 'success') })

$lines = @(
    "Automated dataset refresh: bug-fix candidates collected from ``$Repo`` for ISO week $Week.",
    '',
    '## ✅ Included (passed validation)',
    '',
    'These entries passed `dataset-validation` (build + FAIL_TO_PASS transition) and are included in this PR.',
    ''
)

if ($passed.Count -gt 0) {
    foreach ($entry in $passed) { $lines += (Format-EntryLine -Entry $entry) }
}
else {
    $lines += '_None._'
}

if ($failed.Count -gt 0) {
    $lines += ''
    $lines += '## ❌ Excluded (failed / incomplete validation — documented, not included)'
    $lines += ''
    $lines += 'These entries did not pass validation and are **not** part of this PR''s changes; listed for the record.'
    $lines += ''
    foreach ($entry in $failed) { $lines += (Format-EntryLine -Entry $entry -WithConclusion) }
}

$lines += ''
$lines += '> Draft PR — requires human review. Screening is a static filter only; correctness is proven by the linked validation jobs.'

$lines -join "`n"
```

- [ ] **Step 2: Fixtures + run (the test)**

```powershell
$dir = New-Item -ItemType Directory -Force -Path (Join-Path $env:TEMP 'nprbody2')
@'
[
  { "Id": "microsoft__BCApps-100", "Pr": 100, "Url": "https://github.com/microsoft/BCApps/pull/100" },
  { "Id": "microsoft__BCApps-200", "Pr": 200, "Url": "https://github.com/microsoft/BCApps/pull/200" },
  { "Id": "microsoft__BCApps-300", "Pr": 300, "Url": "https://github.com/microsoft/BCApps/pull/300" }
]
'@ | Set-Content "$dir/collected.json" -Encoding utf8
@'
[
  { "name": "microsoft__BCApps-100", "html_url": "https://gh/run/1/job/11", "conclusion": "success" },
  { "name": "microsoft__BCApps-200", "html_url": "https://gh/run/1/job/22", "conclusion": "failure" }
]
'@ | Set-Content "$dir/jobs.json" -Encoding utf8

$body = .\scripts\New-DatasetPrBody.ps1 -CollectedFile "$dir/collected.json" -JobsFile "$dir/jobs.json" -RunUrl "https://gh/run/1" -Repo "microsoft/BCApps" -Week "29"
$body
```

- [ ] **Step 3: Assertions**

```powershell
# 100 passed -> Included with its job link, no conclusion tag
if ($body -notmatch [regex]::Escape('- `microsoft__BCApps-100` ([PR #100](https://github.com/microsoft/BCApps/pull/100)) — 🔬 [validation](https://gh/run/1/job/11)')) { throw '100 not in Included' }
# 200 failed -> Excluded with conclusion **failure**
if ($body -notmatch [regex]::Escape('- `microsoft__BCApps-200` ([PR #200](https://github.com/microsoft/BCApps/pull/200)) — 🔬 [validation](https://gh/run/1/job/22) — **failure**')) { throw '200 not in Excluded/failure' }
# 300 has no job -> Excluded, incomplete, run-url fallback
if ($body -notmatch [regex]::Escape('- `microsoft__BCApps-300` ([PR #300](https://github.com/microsoft/BCApps/pull/300)) — 🔬 [validation](https://gh/run/1) — **incomplete**')) { throw '300 not incomplete/fallback' }
if ($body -notmatch '## ✅ Included') { throw 'missing Included header' }
if ($body -notmatch '## ❌ Excluded') { throw 'missing Excluded header' }
'ASSERTIONS PASSED'
```

Expected: `ASSERTIONS PASSED`.

- [ ] **Step 4: No-failures case omits the Excluded section**

```powershell
@'
[ { "name": "microsoft__BCApps-100", "html_url": "https://gh/run/1/job/11", "conclusion": "success" } ]
'@ | Set-Content "$dir/jobs-allpass.json" -Encoding utf8
@'
[ { "Id": "microsoft__BCApps-100", "Pr": 100, "Url": "https://github.com/microsoft/BCApps/pull/100" } ]
'@ | Set-Content "$dir/collected-one.json" -Encoding utf8
$body2 = .\scripts\New-DatasetPrBody.ps1 -CollectedFile "$dir/collected-one.json" -JobsFile "$dir/jobs-allpass.json" -RunUrl "https://gh/run/1" -Repo "microsoft/BCApps" -Week "29"
if ($body2 -match '## ❌ Excluded') { throw 'Excluded section should be absent' }
if ($body2 -notmatch '## ✅ Included') { throw 'Included missing' }
'ALLPASS OK'
```

Expected: `ALLPASS OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/New-DatasetPrBody.ps1
git commit -m "feat: split draft-PR body into Included/Excluded by validation result" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: `Remove-DatasetEntries.ps1` — prune by instance-id

**Files:**
- Create: `scripts/Remove-DatasetEntries.ps1`

**Interfaces:**
- Consumes: `-DatasetFile` (path to `bcbench.jsonl`), `-ProblemStatementDir` (path to `problemstatement`), `-InstanceId` (string array).
- Produces: side effects only — removes JSONL lines whose `instance_id` is in the set and deletes each `<ProblemStatementDir>/<instance_id>` directory. No-op when `-InstanceId` is empty or targets are absent.

- [ ] **Step 1: Create the script**

Create `scripts/Remove-DatasetEntries.ps1`:

```powershell
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

if ($InstanceId.Count -eq 0) { return }

$remove = [System.Collections.Generic.HashSet[string]]::new()
foreach ($id in $InstanceId) { [void]$remove.Add([string]$id) }

if (Test-Path $DatasetFile) {
    $kept = foreach ($line in [System.IO.File]::ReadAllLines($DatasetFile)) {
        if (-not $line.Trim()) { continue }
        $id = [string]($line | ConvertFrom-Json).instance_id
        if (-not $remove.Contains($id)) { $line }
    }
    Set-Content -Path $DatasetFile -Value $kept -Encoding utf8
}

foreach ($id in $InstanceId) {
    $dir = Join-Path $ProblemStatementDir ([string]$id)
    if (Test-Path $dir) { Remove-Item -Recurse -Force -Path $dir }
}
```

- [ ] **Step 2: Fixtures + run (the test)**

```powershell
$d = New-Item -ItemType Directory -Force -Path (Join-Path $env:TEMP 'rmentries')
$ds = Join-Path $d 'bcbench.jsonl'
$ps = New-Item -ItemType Directory -Force -Path (Join-Path $d 'problemstatement')
@'
{"instance_id":"keep-1","patch":"a"}
{"instance_id":"drop-1","patch":"b"}
{"instance_id":"keep-2","patch":"c"}
'@ | Set-Content $ds -Encoding utf8
New-Item -ItemType Directory -Force -Path (Join-Path $ps 'keep-1') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ps 'drop-1') | Out-Null
'x' | Set-Content (Join-Path $ps 'drop-1/README.md')

.\scripts\Remove-DatasetEntries.ps1 -DatasetFile $ds -ProblemStatementDir $ps -InstanceId @('drop-1')
```

- [ ] **Step 3: Assertions**

```powershell
$after = @(Get-Content $ds | Where-Object { $_.Trim() } | ForEach-Object { ($_ | ConvertFrom-Json).instance_id })
if ($after -contains 'drop-1') { throw 'drop-1 still present in jsonl' }
if ($after -notcontains 'keep-1' -or $after -notcontains 'keep-2') { throw 'kept entries lost' }
if ($after.Count -ne 2) { throw "expected 2 kept, got $($after.Count)" }
if (Test-Path (Join-Path $ps 'drop-1')) { throw 'drop-1 problemstatement dir not deleted' }
if (-not (Test-Path (Join-Path $ps 'keep-1'))) { throw 'keep-1 problemstatement dir wrongly deleted' }
'ASSERTIONS PASSED'
```

Expected: `ASSERTIONS PASSED`.

- [ ] **Step 4: Empty and missing-target no-op**

```powershell
.\scripts\Remove-DatasetEntries.ps1 -DatasetFile $ds -ProblemStatementDir $ps -InstanceId @()
$stillTwo = @(Get-Content $ds | Where-Object { $_.Trim() })
if ($stillTwo.Count -ne 2) { throw 'empty InstanceId must be a no-op' }
.\scripts\Remove-DatasetEntries.ps1 -DatasetFile (Join-Path $d 'nope.jsonl') -ProblemStatementDir $ps -InstanceId @('ghost')
'NOOP OK'
```

Expected: `NOOP OK` (no throw).

- [ ] **Step 5: Commit**

```bash
git add scripts/Remove-DatasetEntries.ps1
git commit -m "feat: add Remove-DatasetEntries to prune dataset entries by id" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Wait, prune, and branch PR-vs-summary in `collect-and-screen.yml`

**Files:**
- Modify: `.github/workflows/collect-and-screen.yml`

**Interfaces:**
- Consumes: `collected.json`, `jobs.json` (now with `conclusion`), `New-DatasetPrBody.ps1`, `Remove-DatasetEntries.ps1`, `steps.run.outputs.branch`.
- Produces: `steps.validate.outputs.run-url`, `steps.prune.outputs.has-passed`; a pruned branch + draft PR, or a run-summary of failures + deleted branch.

- [ ] **Step 1: Add a job timeout above the wait budget**

Under `jobs.collect-and-screen:`, add `timeout-minutes: 350` right after `runs-on: ubuntu-latest`:

```yaml
  collect-and-screen:
    runs-on: ubuntu-latest
    timeout-minutes: 350
    outputs:
      branch: ${{ steps.run.outputs.branch }}
```

- [ ] **Step 2: Replace the validate step to wait and capture conclusions**

Replace the entire `- name: Trigger validation and resolve job URLs` step (id `validate`) with:

```yaml
      - name: Trigger validation and wait for conclusions
        id: validate
        if: steps.run.outputs.branch != ''
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        shell: pwsh
        run: |
          $ErrorActionPreference = 'Stop'
          $branch = '${{ steps.run.outputs.branch }}'
          $dispatchAt = (Get-Date).ToUniversalTime()

          gh workflow run dataset-validation.yml --ref $branch -f modified-only=true -f test-run=false

          # gh workflow run returns no id, so poll for the run it created.
          $runId = $null
          $runUrl = ''
          for ($i = 0; $i -lt 12; $i++) {
            Start-Sleep -Seconds 5
            $runs = gh run list --workflow dataset-validation.yml --branch $branch --event workflow_dispatch --json databaseId,url,createdAt --limit 5 | ConvertFrom-Json
            $match = $runs | Where-Object { [datetimeoffset]$_.createdAt -ge $dispatchAt.AddSeconds(-60) } |
              Sort-Object { [datetimeoffset]$_.createdAt } -Descending | Select-Object -First 1
            if ($match) { $runId = $match.databaseId; $runUrl = $match.url; break }
          }
          "run-url=$runUrl" | Add-Content $env:GITHUB_OUTPUT

          # Wait for the validation run to finish (~5h budget: 300 x 60s), then read
          # each entry's conclusion. Entries still unfinished at the budget stay
          # non-'success' and are treated as not-passed downstream.
          $jobsJson = '[]'
          if ($runId) {
            for ($i = 0; $i -lt 300; $i++) {
              $status = gh run view $runId --json status --jq '.status'
              if ($status -eq 'completed') { break }
              Start-Sleep -Seconds 60
            }
            $jobsJson = gh api "/repos/${{ github.repository }}/actions/runs/$runId/jobs?per_page=100" --jq '[.jobs[] | {name: .name, html_url: .html_url, conclusion: .conclusion}]'
            if (-not $jobsJson) { $jobsJson = '[]' }
          }
          Set-Content -Path jobs.json -Value $jobsJson -Encoding utf8
```

- [ ] **Step 3: Add the prune step**

Insert this step immediately after the validate step (before the PR step):

```yaml
      - name: Prune entries that did not pass validation
        id: prune
        if: steps.run.outputs.branch != ''
        shell: pwsh
        run: |
          $ErrorActionPreference = 'Stop'
          $branch = '${{ steps.run.outputs.branch }}'

          $collected = @(Get-Content -Raw collected.json | ConvertFrom-Json)
          $jobs = if (Test-Path jobs.json) { @(Get-Content -Raw jobs.json | ConvertFrom-Json) } else { @() }

          $passedIds = @($jobs | Where-Object { $_.conclusion -eq 'success' } | ForEach-Object { [string]$_.name })
          $collectedIds = @($collected | ForEach-Object { [string]$_.Id })
          $notPassed = @($collectedIds | Where-Object { $passedIds -notcontains $_ })
          $passedCount = @($collectedIds | Where-Object { $passedIds -contains $_ }).Count

          Write-Host "collected=$($collectedIds.Count) passed=$passedCount notPassed=$($notPassed.Count)"

          if ($passedCount -gt 0 -and $notPassed.Count -gt 0) {
            .\scripts\Remove-DatasetEntries.ps1 -DatasetFile dataset/bcbench.jsonl -ProblemStatementDir dataset/problemstatement -InstanceId $notPassed
            if (git status --porcelain) {
              git add dataset/bcbench.jsonl dataset/problemstatement
              git commit --amend --no-edit
              git push --force origin $branch
              Write-Host "Pruned $($notPassed.Count) failed entr$(if ($notPassed.Count -eq 1) { 'y' } else { 'ies' }) and force-pushed $branch"
            }
          }

          $hasPassed = if ($passedCount -gt 0) { 'true' } else { 'false' }
          "has-passed=$hasPassed" | Add-Content $env:GITHUB_OUTPUT
```

- [ ] **Step 4: Gate the PR step on has-passed**

Change the `if:` of the `- name: Create or update draft PR` step to also require a passing entry:

```yaml
      - name: Create or update draft PR
        if: steps.run.outputs.branch != '' && steps.prune.outputs.has-passed == 'true'
```

Leave the rest of that step unchanged (it already calls `New-DatasetPrBody.ps1` with `collected.json` / `jobs.json` and uses `DATASET_PR_TOKEN`).

- [ ] **Step 5: Add the 0-passed summary + branch-delete step**

Append this step after the PR step:

```yaml
      - name: Summarize failures and delete branch (no entry passed)
        if: steps.run.outputs.branch != '' && steps.prune.outputs.has-passed == 'false'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        shell: pwsh
        run: |
          $ErrorActionPreference = 'Stop'
          $branch = '${{ steps.run.outputs.branch }}'
          $runUrl = '${{ steps.validate.outputs.run-url }}'

          $collected = @(Get-Content -Raw collected.json | ConvertFrom-Json)
          $jobs = if (Test-Path jobs.json) { @(Get-Content -Raw jobs.json | ConvertFrom-Json) } else { @() }
          $jobMap = @{}
          foreach ($j in $jobs) { if ($j.name) { $jobMap[[string]$j.name] = $j } }

          $lines = @(
            '## Dataset refresh: no entry passed validation',
            '',
            "No PR opened. The following collected candidates failed or did not complete validation ($runUrl):",
            ''
          )
          foreach ($entry in $collected) {
            $job = $jobMap[[string]$entry.Id]
            $url = if ($job -and $job.html_url) { [string]$job.html_url } elseif ($runUrl) { $runUrl } else { '' }
            $conclusion = if ($job -and $job.conclusion) { [string]$job.conclusion } else { 'incomplete' }
            $link = if ($url) { " — 🔬 [validation]($url)" } else { '' }
            $lines += "- ``$($entry.Id)`` ([PR #$($entry.Pr)]($($entry.Url)))$link — **$conclusion**"
          }
          ($lines -join "`n") | Add-Content -Path $env:GITHUB_STEP_SUMMARY

          git push origin --delete $branch
          Write-Host "Deleted branch $branch (no entry passed validation)"
```

- [ ] **Step 6: YAML sanity check**

```powershell
python -c "import yaml; yaml.safe_load(open('.github/workflows/collect-and-screen.yml', encoding='utf-8')); print('YAML OK')"
```

Expected: `YAML OK`. If `yaml` is missing, use `uv run python -c "..."`.

- [ ] **Step 7: Self-review the full file**

Re-read `.github/workflows/collect-and-screen.yml` end-to-end: confirm step order is collect (`run`) → `validate` → `prune` → PR → summary; the PR step and summary step have mutually exclusive `if:` on `steps.prune.outputs.has-passed`; `timeout-minutes: 350` is on the job; indentation and `${{ }}` intact.

- [ ] **Step 8: Commit**

```bash
git add .github/workflows/collect-and-screen.yml
git commit -m "feat: wait for validation, prune failed entries before opening PR" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 9: Live smoke test (controller-run, after push)** — DO NOT run this yourself.

The end-to-end test (`gh workflow run collect-and-screen.yml --ref ...`) waits hours on BC runners and opens/prunes a real PR. The controller runs it. Your verification is Steps 6-7 plus the fixture tests in Tasks 1-2.

---

## Self-Review

**Spec coverage:**
- Wait for validation to finish (§2) → Task 3 Step 2 (poll until `completed`, ~5h). ✓
- Per-eval conclusions in `jobs.json` (§2) → Task 3 Step 2 (`{name, html_url, conclusion}`). ✓
- Prune not-passed from branch (§3) → Task 2 + Task 3 Step 3 (amend + force-push). ✓
- Two-section PR body (§4, ≥1 passed) → Task 1 + Task 3 Step 4. ✓
- 0-passed → summary + delete branch (§4) → Task 3 Step 5. ✓
- "Passed" = `conclusion == 'success'` → Task 1 classification + Task 3 Step 3 `passedIds`. ✓
- Idempotency / draft / DATASET_PR_TOKEN unchanged → PR step left intact (Task 3 Step 4). ✓
- Ordering (§6) → Task 3 Steps 2-5. ✓

**Placeholder scan:** No TBD/TODO; every code step is complete. ✓

**Type consistency:** `{ Id, Pr, Url }` (collected) and `{ name, html_url, conclusion }` (jobs) are used identically in Task 1, Task 3 Step 3, and Task 3 Step 5. `steps.prune.outputs.has-passed` is written in Step 3 and read in Steps 4-5. `steps.validate.outputs.run-url` written in Step 2, read in Steps 4-5. Success rule (`conclusion -eq 'success'`) matches between the body builder (Task 1) and the prune classifier (Task 3 Step 3). ✓
