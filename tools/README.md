# Tools

Standalone scripts for inspecting historical code and analyzing GitHub Actions artifacts.

## `generate_history_report.py`

Creates a Markdown report of recent commits affecting **agent-selected files**, including
the full text diff of each selected commit across **all** its changed files. This exposes
related changes and mirror implementations without narrowing the report to the query files.
It uses only Python's standard library and Git.

```powershell
python .\tools\generate_history_report.py `
    --repo NAV `
    --repo-path C:\depot\NAV `
    --commit <full-dataset-base_commit-sha> `
    --file "App\Layers\W1\BaseApp\Pricing\PriceList\PriceListHeader.Table.al" `
    --file "App\Layers\W1\BaseApp\Pricing\PriceList\PriceListLine.Table.al" `
    --max-commits 5 `
    --output C:\reports\history-01.md
```

| Argument | Meaning |
|---|---|
| `--repo` | `NAV` or `BCApps`; a repository-family label, not a remote lookup or repository-identity check |
| `--repo-path` | Root of the corresponding existing local clone (the evaluation `testbed` in CI) |
| `--commit` | Full 40-character cutoff SHA, normally the entry's `base_commit`; **exclusive** |
| `--file` | Required, repeatable, literal repository-relative file path; one or many files |
| `--max-commits` | Maximum recent matching commits across the union of files; default `5` |
| `--output` | New `.md` file; existing files are never overwritten |

Use **one or more repeatable `--file` arguments**, rather than a mandatory file-list artifact:
the agent can begin with one suspect file, then request another report as it discovers related
files. Spaces and Windows path separators are supported. Directories and revision expressions
are rejected; wildcard characters are literal, not glob patterns. Paths can refer to deleted
historical files. Renames are displayed in commit diffs, but selection does not automatically
follow old names; explicitly supply an older path to investigate its earlier history.

### History boundary and limitations

- Commits must be reachable from the cutoff's parents. The cutoff, descendants, and unrelated
  branches are excluded regardless of their timestamps. Merge cutoffs include both parent
  histories. Results use Git's newest-first topological ordering.
- Full-commit diffs are not filtered to the query files. Merge diffs are against the first
  parent. Sync merges that did not change a selected file against that parent do not consume
  the limit; their relevant ancestor commits can still be selected. Binary changes are
  identified but binary payloads are not embedded.
- The tool does not fetch, clone, checkout, modify tracked files, or consult dataset gold
  patches. It works after the testbed's remote has been removed and disables Git replacement
  objects and automatic lazy fetching.
- CI testbeds currently retain shallow history (default depth 200). Reports explicitly warn
  about shallow history and omit boundary commits whose parent diffs cannot be reconstructed.
  Provision a deeper **cutoff-bounded** history before starting the agent if needed; do not
  restore unrestricted remote access during evaluation.
- The trusted caller must supply the correct repository and cutoff. This read-only helper is
  not an access-control sandbox: it cannot prevent an agent with unrestricted shell access
  from making separate Git or network calls.

### Do not reveal likely fix files before localization

This is an **on-demand** tool, not an automatic dataset preprocessor. Make its generic usage
available without prefilled file names; require the agent to identify suspect files from the
issue and source first, then invoke it with those paths. Do not derive the inputs from `patch`,
`test_patch`, changed-file labels, or other gold artifacts. Do not create or attach a report
before the agent requests history for its own selected files. Requiring paths does not prove
the agent has completed localization; this sequencing is a harness/instruction contract.

No category pipeline, default prompt, or evaluation workflow automatically invokes this tool.
It can be used for a deliberate history-enabled experiment without changing other categories.

### Where this fits in BCAppsBugFix

The existing `bc-fix-bug-v5` skill investigates source in Phase 1, Step 2
(`.github/skills/bc-fix-bug-v5/orchestrator.md`) and already asks for file-scoped
`git log --oneline -10`. The chained `bcfix-plan` skill does the same in Step 4
(`.github/skills/bcfix-plan/SKILL.md`). An opt-in integration should invoke this report
**at that point, after identifying suspect files**, and read it before finalizing the plan.
Keep the report in the agent's per-run temporary state directory, outside tracked source.

Use paths and a cutoff SHA from the **same clone**: NAV's `App\Layers\...` and
`App\Apps\...` layout is not BCAppsBugFix's `src\Layers\...` and `src\Apps\...` layout.
Do not translate paths or treat a NAV SHA as a BCApps/mirror SHA. For a BCAppsBugFix clone,
use `--repo BCApps` to describe the family and `--repo-path` to identify the actual clone;
the report records both. During a benchmark, pin the cutoff to the task's trusted
`base_commit`, never the agent's current HEAD or a moving branch.

The helper neither launches the production bug-fix workflow nor changes its instructions.
In particular, its normal issue-fetch, commit/push, and PR steps should not be enabled
implicitly in a benchmark by providing this history tool.

BCAppsBugFix's `sync-upstream.yml` fetches BCApps and performs a non-squash merge, preserving
the upstream BCApps commits in the local ancestry. Its file-scoped `git log` therefore reads
local history that can include original BCApps commits, not a live query against BCApps.
This does not reconstruct older NAV history when code entered BCApps as a snapshot import.
Use a NAV clone for NAV history and a BCApps-family clone for BCApps history; the requested
cutoff must exist in that clone. The helper never substitutes a different repository or HEAD
when a requested commit is unavailable.

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
