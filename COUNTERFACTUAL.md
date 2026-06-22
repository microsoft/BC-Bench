# Counterfactual Evaluation

This document describes the **counterfactual (CF)** categories in BC-Bench.

## What Are Counterfactual Entries?

A counterfactual (CF) entry is a **variant** of an existing base bug-fix entry. It reuses the same repository state (`repo`, `base_commit`, `project_paths`) but provides a **different fix and test pair** — testing whether an agent can solve a related-but-different version of the same bug.

Each CF entry lives in [`dataset/counterfactual.jsonl`](dataset/counterfactual.jsonl) and references a base entry from [`dataset/bcbench.jsonl`](dataset/bcbench.jsonl).

### Validation Contract

CF entries follow the **exact same** validation contract as bug-fix:

- **Before** applying the patch → `FAIL_TO_PASS` tests **FAIL**
- **After** applying the patch → `FAIL_TO_PASS` tests **PASS**

This means the same `BugFixPipeline` is reused for evaluation.

### Naming Convention

```
microsoftInternal__NAV-210528         ← base entry (in bcbench.jsonl)
microsoftInternal__NAV-210528__cf-1   ← first counterfactual variant
microsoftInternal__NAV-210528__cf-2   ← second variant
```

## The `cf` Category

All CF entries are exposed under a single category named `cf`. The base bug-fix
evaluation pipeline is reused as-is. CF runs in CI **only save raw results**
(per-instance result JSONL files + an aggregated `evaluation_summary.json`
artifact); they do not push to the public leaderboard or upload to Braintrust.
Downstream metrics (resolution rate, family fragility, severity, stability,
etc.) are computed offline from the raw results in the analysis notebooks.

Variant numbering still lives in the instance ID (`<base_id>__cf-<N>`), so any
per-variant analysis remains possible by grouping on the `__cf-N` suffix.

All CF entries share:
- **Dataset file**: `counterfactual.jsonl`
- **Entry class**: `CounterfactualEntry`
- **Pipeline**: `BugFixPipeline` (reused)
- **Result class**: `BugFixResult` (reused)
- **Prompt template**: `counterfactual-template`

## CF Entry Schema

Each line in `counterfactual.jsonl` contains:

| Field                        | Description                                       |
| ---------------------------- | ------------------------------------------------- |
| `instance_id`                | `<base_id>__cf-<N>` — unique identifier           |
| `base_instance_id`           | ID of the base entry this variant is derived from |
| `variant_description`        | Human-readable description of the variant         |
| `failure_layer`              | Optional failure layer classification             |
| `problem_statement_override` | Path to the CF-specific problem statement         |
| `patch`                      | The counterfactual fix patch                      |
| `test_patch`                 | The counterfactual test patch                     |
| `FAIL_TO_PASS`               | Tests that must fail before fix, pass after       |
| `PASS_TO_PASS`               | Tests that must pass both before and after        |

**Note:** Fields like `repo`, `base_commit`, `project_paths`, `environment_setup_version`, and `created_at` are **not stored** in CF entries. They are resolved at load time from the base entry in `bcbench.jsonl`.

## Architecture

The counterfactual categories integrate into BC-Bench's polymorphic category system:

| Extension Point | Value |
|---|---|
| `EvaluationCategory` | `CF = "cf"` |
| `is_counterfactual` | `True` only for `CF` |
| `prompt_template_key` | `"counterfactual"` |
| `dataset_path` | `dataset/counterfactual.jsonl` |
| `entry_class` | `CounterfactualEntry` (resolves base fields at load time) |
| `pipeline` | `BugFixPipeline` (reused — same FAIL→PASS contract) |
| `result_class` | `BugFixResult` (reused) |
| `summary_class` | `ExecutionBasedEvaluationResultSummary` (reused) |

### Key File Reference

| File | Purpose |
|---|---|
| [`dataset/counterfactual.jsonl`](dataset/counterfactual.jsonl) | All CF entries (one JSON per line) |
| [`dataset/problemstatement/<id>/`](dataset/problemstatement/) | Problem statement for each CF entry |
| [`src/bcbench/dataset/counterfactual_entry.py`](src/bcbench/dataset/counterfactual_entry.py) | CF entry model with base resolution |
| [`src/bcbench/types.py`](src/bcbench/types.py) | Category registration (`CF`) |

## CLI Usage

```bash
# List all CF entries
uv run bcbench dataset list --category cf

# List a few random CF entries (test run)
uv run bcbench dataset list --category cf --test-run

# View a specific CF entry
uv run bcbench dataset view microsoftInternal__NAV-210528__cf-1 --category cf

# Run agent on a CF entry
uv run bcbench run copilot microsoftInternal__NAV-210528__cf-1 \
  --category cf \
  --repo-path /path/to/NAV

# Full evaluation (build + test)
uv run bcbench evaluate copilot microsoftInternal__NAV-210528__cf-1 \
  --category cf \
  --repo-path /path/to/NAV
```

## Analysis Notebooks

Experiment notebooks for analyzing CF results are in [`notebooks/counterfactual-evaluation/`](notebooks/counterfactual-evaluation/):

| Notebook | Purpose |
|---|---|
| `experiment1-base-performance.ipynb` | Instance-level compile/pass rates per model |
| `experiment2-cf-sensitivity.ipynb` | Family fragility rate, severity, pattern analysis |
| `experiment3-layered-failure.ipynb` | L1-L5 failure distribution, layer-conditioned fragility |
