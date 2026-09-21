# Tools

Standalone scripts for inspecting historical code and analyzing GitHub Actions artifacts.

## `generate_history_report.py`

Creates a Markdown report from **remote NAV and/or BCApps history** for commits affecting
agent-selected files. Every changed file is listed, but patch content is limited to modified
existing files and a configurable number of distinct filenames. No existing clone or
`--repo-path` is needed.

The script runs on a cloud runner (or locally) with Python and Git. It creates an isolated,
temporary Git object cache per repository, fetches only the supplied cutoff's history, and
deletes the cache afterward. It requests blob filtering so file content can be downloaded
only when needed for historical diffs; server support determines transfer volume. There is
no source checkout and the agent workspace is not changed. This is a remote-backed CLI,
not a deployed web service or a REST-only implementation.

### One repository

```powershell
python .\tools\generate_history_report.py `
    --repo NAV `
    --commit $navBaseCommit `
    --file "App\Layers\W1\BaseApp\Pricing\PriceList\PriceListHeader.Table.al" `
    --max-commits 5 `
    --max-files 10 `
    --output "$env:TEMP\history-01.md"
```

### Both repositories

Each repository needs **its own full cutoff SHA and its own file paths**:

```powershell
python .\tools\generate_history_report.py `
    --repo NAV BCApps `
    --commit "NAV=$navBaseCommit" `
    --commit "BCApps=$bcappsBaseCommit" `
    --file "NAV=App\Layers\W1\BaseApp\Pricing\PriceList\PriceListHeader.Table.al" `
    --file "BCApps=src\Layers\W1\BaseApp\Pricing\PriceList\PriceListHeader.Table.al" `
    --max-commits 5 `
    --max-files 10 `
    --history-depth 200 `
    --output "$env:TEMP\history-both-01.md"
```

Paths above are examples, not prefilled hints for evaluated agents. Use actual paths from
the selected repository at the approved cutoff. A missing path or unavailable cutoff is an
error, not permission to substitute the latest revision.

| Argument | Meaning |
|---|---|
| `--repo` | `NAV`, `BCApps`, or `NAV BCApps`; repeated `--repo` flags also work |
| `--commit` | Exclusive full SHA; exactly one per repo. Qualify as `REPO=SHA` for multiple repos |
| `--file` | Repeatable literal relative path; qualify as `REPO=path` for multiple repos |
| `--max-commits` | Maximum recent matching commits **per repository**, default `5` |
| `--max-files` | Maximum distinct modified filenames whose content is shown **per commit**, default `10` |
| `--history-depth` | Depth fetched starting at each cutoff, default `200` |
| `--output` | New `.md` file; existing files are never overwritten |

The combined report has a separate section and cutoff for each repository. It does not
invent a cross-repository chronological order. Missing/duplicate cutoffs, missing file
selections, and unqualified multi-repo inputs are rejected before remote access. Failure
in either repository prevents a partial report from being emitted as a complete result.

### Authentication and repository resolution

- `NAV` resolves to `https://dev.azure.com/dynamicssmb2/Dynamics%20SMB/_git/NAV`.
  Supply an Entra access token in `ADO_TOKEN`, or a read-scoped PAT in
  `AZURE_DEVOPS_EXT_PAT`. Otherwise the script obtains a token from an already authenticated
  Azure CLI session using the Azure DevOps resource. The identity needs NAV read access.
- `BCApps` resolves to `https://github.com/microsoft/BCApps.git`. It uses `GH_TOKEN` or
  `GITHUB_TOKEN` when supplied; otherwise public access is anonymous.
- Authentication headers are passed through the Git subprocess environment, not command
  arguments, remote URLs, Markdown output, or persisted Git configuration.

### History boundary and limitations

- Only strict ancestors of each cutoff are reported, not the cutoff itself, descendants,
  or unrelated branches. This is a graph boundary, not a timestamp filter. Merge cutoffs
  include both parent histories; results use newest-first topological ordering.
- Fetches name the pinned SHA, never a moving branch or `HEAD`. Additional lazy downloads
  obtain historical objects needed by the bounded history queries and diffs.
- Merge diffs are against the first parent. Sync merges that did not change a selected
  file against that parent do not consume the commit limit. Changes throughout the commit
  are considered, not just the query paths; displayed patch content follows the rules below.
- Shallow history is explicitly marked. Boundary commits without available parents are
  omitted rather than presented as artificial whole-tree additions. Increase
  `--history-depth` to search farther back from the same cutoff.
- Paths are literal, not globs. Deleted historical files can be queried. Renames are shown
  in diffs but old names are not automatically followed; supply the old path explicitly.
- For a benchmark, the trusted harness must approve **all** cutoffs. A NAV task's SHA does
  not define a BCApps snapshot. Do not use current BCApps `HEAD` as a secondary cutoff:
  it may already contain the fix being evaluated. Without an approved secondary snapshot,
  restrict the query to the task's own repository.
- The helper does not read gold patches or infer which files need fixing. It is not an
  access-control sandbox for an agent that already has unrestricted shell/network access.

### Bounded patch content

- Show patch content only for modified existing files (Git status `M`). Added, deleted,
  copied, type-changed, and Git-detected renamed/moved files remain in the complete change
  list with `content omitted`, but never display patch content or consume the file limit.
  Renames with accompanying content changes are also metadata-only.
- Group modifications by case-insensitive **basename**, ignoring their folders.
  For example, `AT/Foo.Codeunit.al`, `DK/Foo.Codeunit.al`, and `W1/Foo.Codeunit.al`
  count as one filename, not three.
- Select the first `--max-files` modified-name groups in Git's reported file order.
  Within each group, show one representative: prefer an explicitly requested path,
  then a `W1` path, then the first occurrence.
- List **all** changed paths and statuses, including other localization copies and names
  beyond the limit. Grouping does not assert their diffs are identical. The representative
  is marked `content shown`; every other path is marked `content omitted`.
- The file limit resets for each commit. A requested file's name may fall beyond the first
  N groups; it still appears in the change list. Increase `--max-files` to see more groups.
  Binary changes never embed binary payloads.

### After localization, not before

Make generic tool usage available without prefilled file names. Require the agent to first
identify suspect files from the issue and source, then request history for those paths.
Do not generate reports from `patch`, `test_patch`, or gold changed-file labels, and do not
attach a report before the agent requests it. Requiring paths does not prove localization;
sequencing and immutable cutoff selection remain a harness/instruction contract.

In BCAppsBugFix, the natural integration points are V5 Phase 1, Step 2
(`.github/skills/bc-fix-bug-v5/orchestrator.md`) and chained `bcfix-plan` Step 4
(`.github/skills/bcfix-plan/SKILL.md`), where the agent already runs file-scoped `git log`.
Keep reports in per-run temporary state, outside tracked source.

The helper queries the named authoritative remote, not the BCAppsBugFix checkout's
current history. BCAppsBugFix's non-squash sync preserves BCApps ancestry, but older NAV
history imported as a snapshot still requires querying NAV with its own approved cutoff.

No category pipeline, default prompt, or agent workflow automatically invokes this tool.
Providing it does not enable the production agent's issue-fetch, commit/push, or PR steps.

## `altest/`

Scripts for analyzing AL test results from BC-Bench GitHub Actions runs:

- **`Get-WorkflowSummary.ps1`** — Fetches workflow run summaries from GitHub Actions, downloads run artifacts, and extracts JSONL result files (even from nested zips).
- **`bcbench_analyze_artifacts.py`** — Extracts, collects, and summarizes test results from downloaded artifact zips or pre-extracted folders. Outputs failure rankings, error variations, and extracted test code.
- **`group_errors_from_summary.py`** — Groups error messages from `errors_summary.csv` into high-level categories for easier triage.

### Usage

Run the scripts from the `tools/altest/` directory. All paths below use placeholders — replace them with your own local paths.

#### 1. Download workflow artifacts

```powershell
cd tools/altest

.\Get-WorkflowSummary.ps1 `
    -Last <N> `
    -Status completed `
    -Category <category> `
    -JsonlOutputRoot <output-dir>
```

| Parameter | Description |
|---|---|
| `-Last` | Number of recent runs to fetch (default: 1) |
| `-Status` | Filter by run status (`completed`, `in_progress`, `queued`, etc.) |
| `-Category` | Filter by evaluation category (e.g. `test-generation`, `bug-fix`) |
| `-JsonlOutputRoot` | Directory to copy discovered JSONL files into (organized by run ID) |
| `-RunId` | Fetch a specific run instead of recent ones |
| `-Branch` | Filter runs by branch name |
| `-KeepArtifacts` | Keep temp artifact download folders (useful for debugging) |

Example:

```powershell
.\Get-WorkflowSummary.ps1 `
    -Last 5 `
    -Status completed `
    -Category test-generation `
    -JsonlOutputRoot C:\Repos\BC-Bench\out2
```

#### 2. Analyze downloaded artifacts

```powershell
python .\bcbench_analyze_artifacts.py `
    --zips-dir <output-dir> `
    --out <analysis-output-dir> `
    --category <category> `
    --top <N>
```

| Parameter | Description |
|---|---|
| `--zips-dir` | Directory from step 1 (the `JsonlOutputRoot`), or any folder with artifact zips |
| `--out` | Directory for analysis output (CSVs, extracted test code, etc.) |
| `--category` | Filter records by category (default: `test-generation`) |
| `--top` | Number of top failing tests to extract (default: 10) |
| `--zip` | Path to a single artifact `.zip` (repeatable) |
| `--extracted-dir` | Directory with already-extracted artifact content |

Example:

```powershell
python .\bcbench_analyze_artifacts.py `
    --zips-dir C:\Repos\BC-Bench\out2 `
    --out C:\Repos\BC-Bench\out `
    --category test-generation `
    --top 10
```

#### 3. Group errors for triage

```powershell
python .\group_errors_from_summary.py <errors-summary-csv> <output-dir>
```

| Argument | Description |
|---|---|
| `<errors-summary-csv>` | Path to `errors_summary.csv` produced by step 2 |
| `<output-dir>` | Directory to write grouped error output |

Example:

```powershell
python .\group_errors_from_summary.py `
    C:\Repos\BC-Bench\out\errors_summary.csv `
    C:\Repos\BC-Bench\out
```
