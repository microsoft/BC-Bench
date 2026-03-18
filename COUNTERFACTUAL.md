# Counterfactual Dataset Authoring

This guide explains **what counterfactual (CF) entries are** and how to create them using the `bcbench dataset` CLI commands.

## What Are Counterfactual Entries?

A counterfactual entry is a **variant** of an existing base benchmark entry. It reuses the same repository state (repo, base commit, project paths) but provides a **different fix and test pair** — testing whether an agent can solve a related-but-different version of the same bug.

Each CF entry lives in [`dataset/counterfactual.jsonl`](dataset/counterfactual.jsonl) and references a base entry from [`dataset/bcbench.jsonl`](dataset/bcbench.jsonl).

**Example:** Base entry tests that all 4 emission fields are enabled. A CF variant tests that only 3 of 4 fields are required.

### Naming Convention

CF entries follow the pattern: `<base_instance_id>__cf-<N>`

```
microsoftInternal__NAV-210528         ← base entry
microsoftInternal__NAV-210528__cf-1   ← first counterfactual variant
microsoftInternal__NAV-210528__cf-2   ← second variant
```

## Authoring Workflow

The workflow has two steps: **extract** a workspace, **edit** the code, then **create** the CF entry.

### Step 1: Extract a workspace

```bash
uv run bcbench dataset cf-extract <base_entry_id> --output-dir ./my-cf-workspace
```

This creates a workspace directory with editable AL files:

```
my-cf-workspace/
├── fix/
│   ├── before/    # Original code before the fix
│   │   └── <path>.al
│   └── after/     # Fixed code — EDIT THIS
│       └── <path>.al
├── test/
│   ├── before/    # Original test code before the fix
│   │   └── <path>.al
│   └── after/     # Test code — EDIT THIS
│       └── <path>.al
└── workspace.json  # Metadata (entry ID, file list, mode)
```

**Options:**

| Flag                 | Description                                                                                |
| -------------------- | ------------------------------------------------------------------------------------------ |
| `--output-dir`, `-o` | Directory to create workspace in (default: `cf-workspace`)                                 |
| `--repo-path`, `-r`  | Path to cloned repo for full-fidelity extraction (extracts complete files, not just hunks) |

**Modes:**

- **Patch-only** (default, no `--repo-path`): Reconstructs files from patch hunks only. Files are padded with empty lines to preserve original line numbers. Fast, no repo needed.
- **Repo-based** (`--repo-path` provided): Checks out the base commit, copies full before/after files. Full fidelity, but requires a local clone.

### Step 2: Edit the code

Open the workspace and modify the `after/` files:

- **`fix/after/`** — Change the fix (the code the agent needs to produce)
- **`test/after/`** — Change the tests (what defines success/failure)

Leave the `before/` files unchanged — they represent the original state.

### Step 3: Create the CF entry

```bash
uv run bcbench dataset cf-create ./my-cf-workspace \
  --variant-description "Only 3 of 4 emission fields required" \
  --intervention-type "test-spec-change"
```

This command:
1. Regenerates patches from your edited `before/` and `after/` files
2. Auto-detects `FAIL_TO_PASS` test procedures from the test patch
3. Assigns the next available `__cf-N` ID
4. Scaffolds a problem statement directory (copies base entry's README.md as template)
5. Appends the new entry to `dataset/counterfactual.jsonl`

**Options:**

| Flag                          | Description                                                                   |
| ----------------------------- | ----------------------------------------------------------------------------- |
| `--variant-description`, `-d` | **Required.** Description of what this variant changes                        |
| `--intervention-type`, `-t`   | Optional. Type of intervention (e.g., `test-spec-change`, `fix-scope-change`) |

### Step 4: Edit the problem statement

After creation, edit the scaffolded problem statement:

```
dataset/problemstatement/<entry_id>/README.md
```

This is copied from the base entry — update it to describe the counterfactual variant's specific requirements.

### Step 5: Commit and PR

```bash
git add dataset/counterfactual.jsonl dataset/problemstatement/
git commit -m "Add counterfactual variant: <description>"
```

## Full Example

```bash
# 1. Extract workspace from a base entry
uv run bcbench dataset cf-extract microsoftInternal__NAV-210528 --output-dir ./cf-sustainability

# 2. Edit the test to only check 3 emission fields instead of 4
#    (open cf-sustainability/test/after/...SustCertificateTest.Codeunit.al and edit)

# 3. Edit the fix to only enable 3 fields
#    (open cf-sustainability/fix/after/...SustainabilitySetup.Table.al and edit)

# 4. Create the CF entry
uv run bcbench dataset cf-create ./cf-sustainability \
  -d "Only 3 of 4 emission fields required: omits Work/Machine Center Emissions" \
  -t "test-spec-change"

# 5. Edit the problem statement
# (edit dataset/problemstatement/microsoftInternal__NAV-210528__cf-1/README.md)

# 6. Commit
git add dataset/ && git commit -m "Add CF variant for NAV-210528"
```

## Evaluating CF Entries

CF entries are evaluated using the same pipeline as bug-fix entries:

```bash
# Run agent on a CF entry
uv run bcbench run copilot microsoftInternal__NAV-210528__cf-1 \
  --category counterfactual-evaluation \
  --repo-path /path/to/NAV

# Full evaluation (build + test)
uv run bcbench evaluate copilot microsoftInternal__NAV-210528__cf-1 \
  --category counterfactual-evaluation \
  --repo-path /path/to/NAV
```

The `--category counterfactual-evaluation` flag tells BC-Bench to use the CF entry's patches and tests for evaluation. The system auto-detects CF entries by their `__cf-N` suffix.

## Listing CF Entries

```bash
# List all entries (includes CF entries by default)
uv run bcbench dataset list

# List without CF entries
uv run bcbench dataset list --no-include-counterfactual
```

## File Reference

| File                                                                                           | Purpose                                                    |
| ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| [`dataset/counterfactual.jsonl`](dataset/counterfactual.jsonl)                                 | All CF entries (one JSON per line)                         |
| [`dataset/problemstatement/<id>/`](dataset/problemstatement/)                                  | Problem statement for each CF entry                        |
| [`src/bcbench/dataset/cf_workspace.py`](src/bcbench/dataset/cf_workspace.py)                   | Core logic: extraction, patch regeneration, entry creation |
| [`src/bcbench/dataset/counterfactual_entry.py`](src/bcbench/dataset/counterfactual_entry.py)   | CF entry Pydantic model                                    |
| [`src/bcbench/dataset/counterfactual_loader.py`](src/bcbench/dataset/counterfactual_loader.py) | Loader for CF entries                                      |
| [`src/bcbench/commands/dataset.py`](src/bcbench/commands/dataset.py)                           | CLI commands (`cf-extract`, `cf-create`)                   |

## CF Entry Schema

Each line in `counterfactual.jsonl` contains:

| Field                        | Description                                       |
| ---------------------------- | ------------------------------------------------- |
| `instance_id`                | `<base_id>__cf-<N>` — unique identifier           |
| `base_instance_id`           | ID of the base entry this variant is derived from |
| `variant_description`        | Human-readable description of the variant         |
| `intervention_type`          | Optional categorization of the change type        |
| `patch`                      | The counterfactual fix patch                      |
| `test_patch`                 | The counterfactual test patch                     |
| `FAIL_TO_PASS`               | Tests that must fail before fix, pass after       |
| `PASS_TO_PASS`               | Tests that must pass both before and after        |
| `problem_statement_override` | Path to the CF-specific problem statement         |
