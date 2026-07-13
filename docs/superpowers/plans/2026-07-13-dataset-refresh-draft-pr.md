# Dataset Refresh Draft PR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the weekly collect-and-screen run pushes its `dataset/week-XX` branch, open (or update) a draft PR listing each newly collected bug-fix entry, with each entry linked to the `dataset-validation` matrix job that tests it.

**Architecture:** Three changes. (1) `scripts/Collect-And-Screen.ps1` gains a `-CollectedFile` param that emits the passed entries as JSON. (2) A new standalone `scripts/New-DatasetPrBody.ps1` turns that JSON plus a resolved `instance_id → job_url` map into a markdown PR body — this holds all the join logic and is unit-verified offline. (3) `.github/workflows/collect-and-screen.yml` wires it together: it passes `-CollectedFile`, resolves the validation run's per-entry job URLs via `gh api`, and creates/updates the draft PR idempotently.

**Tech Stack:** PowerShell 7 (`pwsh`), GitHub Actions, GitHub CLI (`gh`).

## Global Constraints

- Target repo default branch (PR base) is `main`.
- Collect job runs on `ubuntu-latest`; keep it lightweight — no BC container.
- The PR must be **draft** and idempotent per ISO-week branch `dataset/week-XX` (re-runs force-push the same branch → update the existing PR, never error).
- PR body lists each entry as `` - `instance_id` ([PR #n](pr-url)) — 🔬 [validation](job-url) ``; unresolved job URLs fall back to the run-level URL.
- No work-item link, no reviewers, no auto-merge.
- Do NOT introduce a new test framework (no Pester) — repo convention is pytest for Python only; verify pwsh via direct invocation with fixtures.
- Commit trailer on every commit: `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`.

---

## File Structure

- `scripts/Collect-And-Screen.ps1` (modify) — add `-CollectedFile`; add `Pr` to each passed record; write JSON when ≥1 entry passed.
- `scripts/New-DatasetPrBody.ps1` (create) — pure builder: collected JSON + jobs JSON + run-url → markdown body on stdout.
- `.github/workflows/collect-and-screen.yml` (modify) — `pull-requests: write`; pass `-CollectedFile`; resolve run + job URLs; create/update draft PR.

---

### Task 1: Emit collected entries as JSON from `Collect-And-Screen.ps1`

**Files:**
- Modify: `scripts/Collect-And-Screen.ps1` (param block ~31-37; passed-record add ~71-72; end of file ~104)

**Interfaces:**
- Produces: a JSON file (path given by `-CollectedFile`) containing an array of `{ "Id": string, "Pr": int, "Url": string }`, one per collected entry. Consumed by `New-DatasetPrBody.ps1` (Task 2) and the workflow (Task 3).

- [ ] **Step 1: Add the `-CollectedFile` parameter**

In the `param(...)` block, add a new parameter after `$SummaryFile`:

```powershell
[CmdletBinding()]
param(
    [string]$Repo = 'microsoft/BCApps',
    [int]$SinceDays = 7,
    [int]$Limit = 200,
    [string]$BaseBranch = 'main',
    [string]$SummaryFile,
    [string]$CollectedFile
)
```

- [ ] **Step 2: Record the PR number on each passed entry**

Change the passed-record creation (currently `@{ Id = $instanceId; Url = ... }`) to also carry `Pr`:

```powershell
            $instanceId = "$($Repo -replace '/', '__')-$pr"
            $passed.Add([PSCustomObject]@{ Id = $instanceId; Pr = $pr; Url = "https://github.com/$Repo/pull/$pr" })
            Write-Log "Collected PR #$pr -> $instanceId" -Level Success
```

- [ ] **Step 3: Write the collected JSON at end of script**

After the existing `if ($SummaryFile) { ... }` block, append:

```powershell
if ($CollectedFile -and $passed.Count -gt 0) {
    $passed | ConvertTo-Json -AsArray -Depth 4 | Set-Content -Path $CollectedFile -Encoding utf8
    Write-Log "Wrote $($passed.Count) collected entr$(if ($passed.Count -eq 1) { 'y' } else { 'ies' }) to $CollectedFile" -Level Info
}
```

- [ ] **Step 4: Syntax-check the script**

Run:

```powershell
pwsh -NoProfile -Command "[System.Management.Automation.Language.Parser]::ParseFile('scripts/Collect-And-Screen.ps1', [ref]$null, [ref]$null) | Out-Null; 'OK'"
```

Expected: prints `OK` with no parse errors.

- [ ] **Step 5: Commit**

```bash
git add scripts/Collect-And-Screen.ps1
git commit -m "feat: emit collected entries as JSON from Collect-And-Screen" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: `New-DatasetPrBody.ps1` — build the PR body markdown

**Files:**
- Create: `scripts/New-DatasetPrBody.ps1`

**Interfaces:**
- Consumes: `-CollectedFile` (JSON array of `{ Id, Pr, Url }` from Task 1); optional `-JobsFile` (JSON array of `{ name, html_url }`); `-RunUrl` fallback string; `-Repo` and `-Week` strings.
- Produces: markdown PR body printed to stdout (single string). Consumed by the workflow (Task 3).

- [ ] **Step 1: Create the script**

Create `scripts/New-DatasetPrBody.ps1`:

```powershell
<#
.SYNOPSIS
Build the markdown body for the dataset-refresh draft PR.

.DESCRIPTION
Joins collected entries (from Collect-And-Screen.ps1 -CollectedFile) to their
dataset-validation matrix-job URLs, producing a markdown bullet per entry. An
entry whose job URL cannot be resolved falls back to the run-level URL.
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

$entries = @(Get-Content -Raw -Path $CollectedFile | ConvertFrom-Json)

$jobMap = @{}
if ($JobsFile -and (Test-Path $JobsFile)) {
    foreach ($job in @(Get-Content -Raw -Path $JobsFile | ConvertFrom-Json)) {
        if ($job.name) { $jobMap[[string]$job.name] = [string]$job.html_url }
    }
}

$lines = @(
    "Automated dataset refresh: bug-fix candidates collected from ``$Repo`` for ISO week $Week.",
    '',
    'Each entry links to the `dataset-validation` job that builds it and checks the FAIL_TO_PASS transition (test fails on base, passes after the gold patch). **Merge only once every linked job is green.**',
    ''
)

foreach ($entry in $entries) {
    $url = if ($jobMap.ContainsKey([string]$entry.Id)) { $jobMap[[string]$entry.Id] } elseif ($RunUrl) { $RunUrl } else { $null }
    $validation = if ($url) { " — 🔬 [validation]($url)" } else { '' }
    $lines += "- ``$($entry.Id)`` ([PR #$($entry.Pr)]($($entry.Url)))$validation"
}

$lines += ''
$lines += '> Draft PR — requires human review. Screening is a static filter only; correctness is proven by the linked validation jobs.'

$lines -join "`n"
```

- [ ] **Step 2: Write fixtures and run the script (the test)**

Create fixture files in a temp dir and run the script. One entry has a matching job (gets a job link), the other has none (falls back to the run URL):

```powershell
$dir = New-Item -ItemType Directory -Force -Path (Join-Path $env:TEMP 'nprbody')
@'
[
  { "Id": "microsoft__BCApps-100", "Pr": 100, "Url": "https://github.com/microsoft/BCApps/pull/100" },
  { "Id": "microsoft__BCApps-200", "Pr": 200, "Url": "https://github.com/microsoft/BCApps/pull/200" }
]
'@ | Set-Content "$dir/collected.json" -Encoding utf8
@'
[ { "name": "microsoft__BCApps-100", "html_url": "https://github.com/microsoft/BC-Bench/actions/runs/1/job/11" } ]
'@ | Set-Content "$dir/jobs.json" -Encoding utf8

$body = .\scripts\New-DatasetPrBody.ps1 -CollectedFile "$dir/collected.json" -JobsFile "$dir/jobs.json" -RunUrl "https://github.com/microsoft/BC-Bench/actions/runs/1" -Repo "microsoft/BCApps" -Week "29"
$body
```

- [ ] **Step 3: Assert the output (the test assertions)**

Run these checks; any failure throws:

```powershell
if ($body -notmatch [regex]::Escape('`microsoft__BCApps-100` ([PR #100](https://github.com/microsoft/BCApps/pull/100)) — 🔬 [validation](https://github.com/microsoft/BC-Bench/actions/runs/1/job/11)')) { throw 'entry-100 job link missing' }
if ($body -notmatch [regex]::Escape('`microsoft__BCApps-200` ([PR #200](https://github.com/microsoft/BCApps/pull/200)) — 🔬 [validation](https://github.com/microsoft/BC-Bench/actions/runs/1)')) { throw 'entry-200 run-url fallback missing' }
if ($body -notmatch 'ISO week 29') { throw 'week header missing' }
'ASSERTIONS PASSED'
```

Expected: prints `ASSERTIONS PASSED`.

- [ ] **Step 4: Verify no-jobs-file fallback**

```powershell
$body2 = .\scripts\New-DatasetPrBody.ps1 -CollectedFile "$dir/collected.json" -RunUrl "https://example/run" -Repo "microsoft/BCApps" -Week "29"
if ($body2 -notmatch [regex]::Escape('🔬 [validation](https://example/run)')) { throw 'missing run-url fallback when no jobs file' }
'FALLBACK OK'
```

Expected: prints `FALLBACK OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/New-DatasetPrBody.ps1
git commit -m "feat: add New-DatasetPrBody for dataset-refresh draft PR body" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Wire the draft-PR flow into `collect-and-screen.yml`

**Files:**
- Modify: `.github/workflows/collect-and-screen.yml` (permissions ~2-4; script invocation ~61-66; trigger step ~79-83; add PR step)

**Interfaces:**
- Consumes: `collected.json` (Task 1), `New-DatasetPrBody.ps1` (Task 2), `jobs.json` (produced in this task), `steps.run.outputs.branch`.
- Produces: a draft PR on `main` from the `dataset/week-XX` branch. No downstream consumer.

- [ ] **Step 1: Grant `pull-requests: write`**

Update the top-level `permissions` block:

```yaml
permissions:
  contents: write
  actions: write
  pull-requests: write
```

- [ ] **Step 2: Pass `-CollectedFile` to the collect script**

In the "Discover, screen, and collect passing PRs" step, add the `-CollectedFile` argument to the `Collect-And-Screen.ps1` call:

```yaml
          .\scripts\Collect-And-Screen.ps1 `
            -Repo '${{ inputs.repo || 'microsoft/BCApps' }}' `
            -SinceDays ${{ inputs.since-days || '7' }} `
            -Limit ${{ inputs.limit || '50' }} `
            -BaseBranch '${{ inputs.base-branch || 'main' }}' `
            -SummaryFile $env:GITHUB_STEP_SUMMARY `
            -CollectedFile "$PWD/collected.json"
```

- [ ] **Step 3: Replace the trigger step with a trigger-and-resolve step**

Replace the existing "Trigger dataset validation on pushed branch" step with one that dispatches validation, resolves the run URL, and writes a per-entry `jobs.json`:

```yaml
      - name: Trigger validation and resolve job URLs
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

          # Matrix jobs only exist after get-entries expands them; poll until more than
          # the single get-entries job is present (or budget runs out).
          $jobsJson = '[]'
          if ($runId) {
            for ($i = 0; $i -lt 24; $i++) {
              Start-Sleep -Seconds 10
              $jobsJson = gh api "/repos/${{ github.repository }}/actions/runs/$runId/jobs?per_page=100" --jq '[.jobs[] | {name: .name, html_url: .html_url}]'
              if (-not $jobsJson) { $jobsJson = '[]' }
              if ((@($jobsJson | ConvertFrom-Json)).Count -gt 1) { break }
            }
          }
          Set-Content -Path jobs.json -Value $jobsJson -Encoding utf8
```

- [ ] **Step 4: Add the create-or-update draft PR step**

Append after the validate step:

```yaml
      - name: Create or update draft PR
        if: steps.run.outputs.branch != ''
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        shell: pwsh
        run: |
          $ErrorActionPreference = 'Stop'
          $branch = '${{ steps.run.outputs.branch }}'
          $repo = '${{ inputs.repo || 'microsoft/BCApps' }}'
          $week = $branch -replace '^dataset/week-', ''

          # Ensure the label exists; ignore "already exists".
          gh label create dataset --color 1f6feb --description 'Automated dataset refresh candidates' 2>$null | Out-Null

          .\scripts\New-DatasetPrBody.ps1 `
            -CollectedFile collected.json `
            -JobsFile jobs.json `
            -RunUrl '${{ steps.validate.outputs.run-url }}' `
            -Repo $repo `
            -Week $week | Set-Content -Path pr-body.md -Encoding utf8

          $title = "Dataset refresh: week $week candidates from $repo"
          $existing = gh pr list --head $branch --state open --json number --jq '.[0].number'
          if ($existing) {
            gh pr edit $existing --title $title --body-file pr-body.md
            Write-Host "Updated draft PR #$existing"
          }
          else {
            gh pr create --draft --base main --head $branch --title $title --body-file pr-body.md --label dataset
          }
```

- [ ] **Step 5: YAML sanity check**

Run (best-effort; skip if PyYAML unavailable):

```powershell
python -c "import yaml; yaml.safe_load(open('.github/workflows/collect-and-screen.yml', encoding='utf-8')); print('YAML OK')"
```

Expected: prints `YAML OK`. If it errors with `ModuleNotFoundError: yaml`, run `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/collect-and-screen.yml', encoding='utf-8')); print('YAML OK')"` instead, or rely on the smoke test below.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/collect-and-screen.yml
git commit -m "feat: open draft PR with per-eval validation links in collect-and-screen" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 7: Live smoke test (manual, after push)**

Push the branch and dispatch the workflow with a tiny window so it runs quickly:

```bash
git push -u origin feature/dataset-refresh-draft-pr
gh workflow run collect-and-screen.yml --ref feature/dataset-refresh-draft-pr -f since-days=3 -f limit=3
gh run watch $(gh run list --workflow collect-and-screen.yml --branch feature/dataset-refresh-draft-pr --limit 1 --json databaseId --jq '.[0].databaseId')
```

Expected outcomes to confirm:
- The run succeeds.
- If ≥1 candidate was collected: a **draft** PR exists on `main` from `dataset/week-XX` (`gh pr list --state open --draft`), its body lists each entry with a `🔬 [validation](...)` link, and it carries the `dataset` label.
- Re-running the dispatch in the same ISO week updates that same PR instead of failing.
- If no candidates were collected: no PR is opened.

Note the entry↔job name match in `New-DatasetPrBody` assumes the validation matrix job's API `name` equals the `instance_id` (the workflow sets `name: ${{ matrix.entry }}`). If the smoke test shows entries falling back to the run URL, inspect `gh api /repos/<owner>/BC-Bench/actions/runs/<id>/jobs --jq '.jobs[].name'` and adjust the match. Clean up the smoke-test PR/branch afterward.

---

## Self-Review

**Spec coverage:**
- Data hand-off (`-CollectedFile` JSON) → Task 1. ✓
- Trigger validation + resolve per-eval job URLs → Task 3 Step 3. ✓
- Create-or-update draft PR, label, title, per-eval links → Task 2 + Task 3 Step 4. ✓
- `pull-requests: write` → Task 3 Step 1. ✓
- Ordering (push → trigger/resolve → PR) → Task 3 Steps 3-4. ✓
- Idempotency per ISO-week branch → Task 3 Step 4 (`gh pr list --head` → edit vs create); verified Task 3 Step 7. ✓
- Two-stage validation context is explanatory only (no code). ✓
- Success criteria (draft PR with per-eval links; same-week update; no-candidates → no PR) → Task 3 Step 7. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `{ Id, Pr, Url }` produced in Task 1 is consumed identically in Task 2 (`$entry.Id/.Pr/.Url`). Jobs shape `{ name, html_url }` produced in Task 3 Step 3 matches Task 2's `$job.name/.html_url`. `steps.validate.outputs.run-url` set in Step 3, read in Step 4. `collected.json` / `jobs.json` filenames consistent across Tasks 1-3. ✓
