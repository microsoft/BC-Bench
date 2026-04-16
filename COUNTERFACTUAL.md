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

## Category Splitting by Variant Number

Instead of a single `counterfactual-evaluation` category, CF entries are split into **separate categories** by their variant number (`cf-1`, `cf-2`, `cf-3`, `cf-4`). This enables running each variant set as a separate GitHub Actions workflow, reducing per-run job count.

| Category | Entries | Description |
|----------|---------|-------------|
| `cf-1`   | ~101    | First counterfactual variant of each base entry |
| `cf-2`   | ~92     | Second variant |
| `cf-3`   | ~56     | Third variant |
| `cf-4`   | ~6      | Fourth variant |

All CF categories share:
- **Dataset file**: `counterfactual.jsonl` (filtered by variant suffix at load time)
- **Entry class**: `CounterfactualEntry`
- **Pipeline**: `BugFixPipeline` (reused)
- **Result class**: `BugFixResult` (reused)
- **Prompt template**: `counterfactual-template` (shared across all CF categories)

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
| `EvaluationCategory` | `CF_1 = "cf-1"`, `CF_2 = "cf-2"`, `CF_3 = "cf-3"`, `CF_4 = "cf-4"` |
| `is_counterfactual` | `True` for all CF categories |
| `cf_variant` | `1`, `2`, `3`, or `4` (parsed from category value) |
| `prompt_template_key` | `"counterfactual"` (shared across all CF categories) |
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
| [`src/bcbench/types.py`](src/bcbench/types.py) | Category registration (`CF_1`–`CF_4`) |

## CLI Usage

```bash
# List all cf-1 entries
uv run bcbench dataset list --category cf-1

# List all cf-2 entries
uv run bcbench dataset list --category cf-2

# List 2 random cf-1 entries (test run)
uv run bcbench dataset list --category cf-1 --test-run

# View a specific CF entry
uv run bcbench dataset view microsoftInternal__NAV-210528__cf-1 --category cf-1

# Run agent on a CF entry
uv run bcbench run copilot microsoftInternal__NAV-210528__cf-1 \
  --category cf-1 \
  --repo-path /path/to/NAV

# Full evaluation (build + test)
uv run bcbench evaluate copilot microsoftInternal__NAV-210528__cf-1 \
  --category cf-1 \
  --repo-path /path/to/NAV
```

## Analysis Notebooks

Experiment notebooks for analyzing CF results are in [`notebooks/counterfactual-evaluation/`](notebooks/counterfactual-evaluation/):

| Notebook | Purpose |
|---|---|
| `experiment1-base-performance.ipynb` | Instance-level compile/pass rates per model |
| `experiment2-cf-sensitivity.ipynb` | Family fragility rate, severity, pattern analysis |
| `experiment3-layered-failure.ipynb` | L1-L5 failure distribution, layer-conditioned fragility |
