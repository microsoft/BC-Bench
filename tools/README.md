# Tools

Standalone scripts for downloading and analyzing GitHub Actions artifacts.

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
