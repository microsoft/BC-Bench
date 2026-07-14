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
newly added entries. This feature **waits for that validation run to finish**,
then includes only the entries that passed in the draft PR's diff and documents
the ones that failed in the PR description — so no human has to manually remove
failed candidates after the fact.

## Goal

After the weekly collect-and-screen run pushes its branch, wait for validation of
the newly collected bug-fix entries, then open (or update) a draft PR whose diff
contains **only the entries that passed**, with the failed/incomplete ones
documented (not included) — each entry linked to the validation job that tests
it.

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

### 2. Trigger validation, wait, and resolve per-eval conclusions

Enhance the existing "Trigger dataset validation" step (gated on
`steps.run.outputs.branch != ''`) so that, after dispatching
`dataset-validation.yml` on the branch, it **waits for the run to finish** and
records each new eval's conclusion and job URL:

- `gh workflow run` does not return a run id, so poll
  `gh run list --workflow dataset-validation.yml --branch $branch --event
  workflow_dispatch --json databaseId,url,createdAt --limit 5`, selecting the
  newest run created at/after the dispatch time (short sleep + a few retries).
- Poll `gh run view $runId --json status` until `status == 'completed'` or a
  **~5-hour budget** elapses (the GitHub job hard cap is 6h; keep margin).
- `dataset-validation.yml` runs a matrix with one job per entry, each named by
  its `instance_id` (`name: ${{ matrix.entry }}`) and running
  `Verify-BuildAndTests` on that entry. Read per-eval results via
  `gh api /repos/{owner}/{repo}/actions/runs/{run_id}/jobs --paginate`, matching
  `job.name == instance_id`, and emit `jobs.json` =
  `[{ name, html_url, conclusion }]`.
- **Passed** = `conclusion == 'success'`. Any other conclusion, or a job still
  unfinished at the budget, counts as **not passed**.
- All URLs are best-effort: the run URL falls back to empty and any unresolved
  eval falls back to the run-level URL.

### 3. Prune failed entries from the branch

New helper `scripts/Remove-DatasetEntries.ps1` takes a list of instance-ids and
removes them from the working tree:

- drop matching lines from `dataset/bcbench.jsonl` (JSONL keyed by `instance_id`);
- delete each `dataset/problemstatement/<instance_id>` directory.

The workflow computes the not-passed set (collected ids minus passed ids) from
`collected.json` + `jobs.json`, runs the prune, and if anything was pruned,
`git commit --amend --no-edit` + force-push — so the branch diff (and therefore
the PR) contains **only passing entries**. Validation already ran against the
pre-prune branch (all entries), so failed jobs still exist and remain linkable.

### 4. Create the draft PR, or summarize failures

After pruning, branch on how many entries passed:

- **≥1 passed** — create/update the draft PR:
  1. Ensure the `dataset` label exists (`gh label create dataset ...`, ignoring
     "already exists").
  2. Build the PR body (`New-DatasetPrBody.ps1`) with two sections driven by
     `conclusion` in `jobs.json`:
     - `## ✅ Included (passed validation)` — passed entries, each
       `` - `instance_id` ([PR #n](pr-url)) — 🔬 [validation](job-url) ``. These
       are in the diff.
     - `## ❌ Excluded (failed / incomplete validation — documented, not
       included)` — the not-passed entries, each with its 🔬 job link and
       conclusion. **Not** in the diff. Section omitted when empty.
  3. Idempotent create-or-update: `gh pr list --head $branch` → `gh pr edit`
     (refresh title/body) if a PR exists, else `gh pr create --draft --base main
     --head $branch --title <title> --body-file <file> --label dataset`.
  4. Title: `Dataset refresh: week <XX> candidates from <repo>`. No work-item link.
- **0 passed** — do not open a PR. Write the failed entries + their validation
  links to `$GITHUB_STEP_SUMMARY`, and delete the now-pointless remote
  `dataset/week-XX` branch (`git push origin --delete`) so no orphan is left.

### 5. Permissions and PR-creation token

Add `pull-requests: write` to the workflow `permissions` block (currently
`contents: write`, `actions: write`).

`pull-requests: write` alone is **not sufficient** in this org. When the
repository/org policy *"Allow GitHub Actions to create and approve pull
requests"* is disabled, the default `GITHUB_TOKEN` is blocked from
`createPullRequest` (the run fails with *"GitHub Actions is not permitted to
create or approve pull requests"*). The PR-creation step therefore authenticates
with a dedicated token:

```yaml
GH_TOKEN: ${{ secrets.DATASET_PR_TOKEN || secrets.GITHUB_TOKEN }}
```

- **`DATASET_PR_TOKEN`** — a repo secret holding a fine-grained PAT (or GitHub
  App installation token) with **Contents: write** + **Pull requests: write** on
  the BC-Bench repo. This is the operational requirement to make the feature
  work while the org policy stays off; a PAT-opened PR also triggers CI on the
  draft, which is desirable.
- The `|| secrets.GITHUB_TOKEN` fallback is used only when `DATASET_PR_TOKEN` is
  unset, and works solely if the org policy above is enabled.

Only the PR-creation step needs this token; branch push and the validation
dispatch continue to use `GITHUB_TOKEN` (`contents: write` / `actions: write`).

### 6. Ordering

push all collected → dispatch `dataset-validation.yml` and **wait** for it to
complete → resolve per-eval conclusions → prune not-passed entries and
force-push → if ≥1 passed, create/update the draft PR (passed in the diff,
failed documented in the body); if 0 passed, summarize failures and delete the
branch.

## Out of scope

- Running `Verify-BuildAndTests` inside the collect job (it runs in the separate
  `dataset-validation` run; the collect job only waits on it).
- Auto-merging or auto-approving.
- Linking the work item.
- Requesting reviewers.

## Success criteria

- A run that collects ≥1 candidate waits for `dataset-validation` to finish, then
  opens/updates a draft PR on `dataset/week-XX` whose **diff contains only the
  entries that passed** validation.
- The PR body has an ✅ Included section (passed, in the diff) and, when any
  failed, an ❌ Excluded section documenting them with their validation-job links.
- Each listed entry links to its own `dataset-validation.yml` matrix job (or the
  run-level URL if the job could not be resolved).
- If **0** entries pass, no PR is opened; the failures are written to the run
  summary and the branch is deleted.
- Re-running in the same ISO week re-collects, re-validates, re-prunes, and
  updates the existing PR instead of erroring.
- A run that collects nothing opens no PR.
