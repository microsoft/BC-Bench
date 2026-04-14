# Tools

Standalone scripts for downloading and analyzing GitHub Actions artifacts.

## `altest/`

Scripts for analyzing AL test results from BC-Bench GitHub Actions runs:

- **`bcbench_analyze_artifacts.py`** — Extracts, collects, and summarizes test results from downloaded artifact zips or pre-extracted folders. Outputs failure rankings, error variations, and extracted test code.
- **`group_errors_from_summary.py`** — Groups error messages from `errors_summary.csv` into high-level categories for easier triage.
