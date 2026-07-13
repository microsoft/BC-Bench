# Dataset refresh: draft PR for collected candidates

## Context

Work item [632829](https://dynamicssmb2.visualstudio.com/Dynamics%20SMB/_workitems/edit/632829)
calls for a semi-automated dataset refresh so BC-Bench stays current and resists
contamination. Haoran added `collect-and-screen.yml` (which calls
`scripts/Collect-And-Screen.ps1`) that discovers merged BCApps PRs, screens them
with `bcbench collect`, writes passing entries into `dataset/bcbench.jsonl` +
`dataset/problemstatement`, force-pushes them to a per-ISO-week branch
`dataset/week-XX`, and triggers `dataset-validation.yml` on that branch.

**Gap:** the job never opens a pull request, so the collected candidates sit on a
branch that a human has to find. This spec closes that gap by opening a **draft
PR** with the new bug-fix dataset additions, keeping a human in the review loop.

## Validation context (two stages)

Correctness of a bug-fix entry is proven in two stages, and this feature relies
on the second one:

1. **Collection-time (static)** — `bcbench collect screen` only checks that the
   PR *has* the required parts: ≥2 project paths, a non-empty fix patch (the gold
   patch), a non-empty test patch, and ≥1 extractable `FAIL_TO_PASS` function. It
   does not build or run anything and explicitly requires manual review.
2. **Validation-time (execution-based)** — `dataset-validation.yml` →
   `Verify-BuildAndTests.ps1` checks out `base_commit`, applies the test patch
   and asserts `FAIL_TO_PASS` **fails** (bug reproduced), then applies the gold
   patch and asserts `FAIL_TO_PASS` **passes** (fix works), with `PASS_TO_PASS`
   green throughout. This is the real fail→pass proof.

The existing collect-and-screen job already triggers stage 2 on the pushed
branch with `--modified-only`, which scopes `Verify-BuildAndTests` to exactly the
newly added entries. This feature **surfaces that validation run on the draft
PR** so a reviewer merges only once it is green. The PR is still created
independent of (does not wait on) the validation result.

## Goal

After the weekly collect-and-screen run pushes its branch, open (or update) a
draft PR that surfaces the newly collected bug-fix dataset entries — each linked
to the validation job that tests that exact entry — for human review.

## Design

### 1. Data hand-off (script)

`Collect-And-Screen.ps1` currently exposes the passed-entries list only inside
its markdown step-summary. Add a `-CollectedFile <path>` parameter that writes
the passed entries as structured JSON so the workflow can build a PR body from
data rather than re-parsing markdown:

```json
[
  { "Id": "microsoft__BCApps-12345", "Pr": 12345, "Url": "https://github.com/microsoft/BCApps/pull/12345" }
]
```

- The file is written only when there is at least one passed entry.
- `-SummaryFile` behaviour is unchanged.

### 2. Trigger validation and resolve per-eval job URLs

Enhance the existing "Trigger dataset validation" step (gated on
`steps.run.outputs.branch != ''`) so that, after dispatching
`dataset-validation.yml` on the branch, it resolves the run and each new eval's
matrix-job URL, exposing them as step output(s):

- `gh workflow run` does not return a run id, so poll
  `gh run list --workflow dataset-validation.yml --branch $branch --event
  workflow_dispatch --json databaseId,url,createdAt --limit 5`, selecting the
  newest run created at/after the dispatch time (short sleep + a few retries).
- `dataset-validation.yml` runs a matrix with one job per entry, each named by
  its `instance_id` (`name: ${{ matrix.entry }}`) and running
  `Verify-BuildAndTests` on that entry. Resolve per-eval job URLs via
  `gh api /repos/{owner}/{repo}/actions/runs/{run_id}/jobs --paginate` and match
  `job.name == instance_id` → `job.html_url`.
- Matrix jobs only exist after the reusable `get-entries` job expands the matrix
  (~1–2 min), so poll the jobs API with a bounded budget (a few minutes). Emit a
  map of `instance_id → job_url`.
- All URLs are best-effort: the run URL falls back to empty and any unresolved
  eval falls back to the run-level URL, so the PR is always created regardless.

### 3. Workflow step (create-or-update draft PR)

Add a step to the `collect-and-screen` job, after the validation-trigger step,
gated on `steps.run.outputs.branch != ''`:

1. Ensure the `dataset` label exists (`gh label create dataset ...`, ignoring an
   "already exists" failure).
2. Build the PR body from the collected JSON, joining each entry to its resolved
   job URL: a short header plus a bullet list of
   `` - `instance_id` (PR #n) — 🔬 [validation](job-url) ``. An eval whose job
   URL could not be resolved links to the run-level URL instead.
3. Idempotent create-or-update, because re-running within the same ISO week
   force-pushes to the same branch:
   - `gh pr list --head $branch` → if a PR exists, `gh pr edit` refreshes its
     title/body.
   - Otherwise `gh pr create --draft --base main --head $branch --title <title>
     --body-file <file> --label dataset`.
4. Title: `Dataset refresh: week <XX> candidates from <repo>`.
5. No work-item link in the body.

### 4. Permissions

Add `pull-requests: write` to the workflow `permissions` block (currently
`contents: write`, `actions: write`).

### 5. Ordering

push → trigger `dataset-validation.yml` (resolve per-eval job URLs) →
create/update draft PR with the entry list, each entry linked to its validation
job. The PR does **not** wait on validation results; the run finishes in parallel
and the reviewer merges once each entry's job is green.

## Out of scope

- Gating PR creation on validation results (we link the run, we do not block on it).
- Running `Verify-BuildAndTests` inside the collect job.
- Auto-merging or auto-approving.
- Linking the work item.
- Requesting reviewers.

## Success criteria

- A weekly (or manual) run that collects ≥1 candidate opens a draft PR on
  `dataset/week-XX` containing the entry list.
- Each listed entry links to its own `dataset-validation.yml` matrix job (or
  falls back to the run-level URL if the job could not be resolved in time).
- Re-running in the same ISO week updates the existing PR instead of erroring.
- A run that collects nothing opens no PR.
