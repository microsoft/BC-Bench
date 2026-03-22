---
description: "Create counterfactual (CF) dataset entries for BC-Bench. Provide the base instance_id and describe the code changes for each variant."
mode: agent
---

# Create Counterfactual Dataset Entries

You are helping create counterfactual (CF) entries for the BC-Bench benchmark dataset.

## Context

Read these files first to understand the workflow:
- `COUNTERFACTUAL.md` — authoring guide
- `dataset/bcbench.jsonl` — find the base entry by instance_id
- `dataset/counterfactual.jsonl` — existing CF entries (match format/key ordering)

## Input Required from User

The user will provide:
1. **Base instance_id** — e.g. `microsoftInternal__NAV-224009`
2. **CF variants** — for each variant:
   - What code changes to make in `test/after/` (test modifications)
   - What code changes to make in `fix/after/` (fix modifications, often unchanged)
   - A short variant description
   - The intervention type (`test-spec-change`, `fix-scope-change`, etc.)
3. **Problem statement** — either a pre-written README path or content to generate

## Workflow (per variant)

### Step 1: Analyze the base entry
```bash
python -c "import json; [print(json.dumps(json.loads(l), indent=2)) for l in open('dataset/bcbench.jsonl') if '<BASE_ID>' in l]"
```
- Understand the patch (fix) and test_patch (test) diffs
- Read the base problem statement from `dataset/problemstatement/<instance_id>/README.md`

### Step 2: Extract workspace
```bash
uv run bcbench dataset cf-extract <base_instance_id> -o cf-<short-name>
```
- Patch-only mode creates padded files — use `Get-Content ... | Where-Object { $_.Trim() }` to view content

### Step 3: Edit the after/ files
- Apply the user's described code changes to `test/after/` and/or `fix/after/`
- If the fix needs to be **reversed** (e.g. CF removes a filter instead of adding one), swap fix/before and fix/after contents:
  ```powershell
  $before = Get-Content "fix\before\<path>" -Raw
  $after = Get-Content "fix\after\<path>" -Raw
  Set-Content "fix\before\<path>" -Value $after -NoNewline
  Set-Content "fix\after\<path>" -Value $before -NoNewline
  ```
- Verify edits with `Get-Content ... | Where-Object { $_.Trim() }`

### Step 4: Create the CF entry
```bash
uv run bcbench dataset cf-create ./cf-<short-name> \
  -d "<variant description>" \
  -t "<intervention-type>"
```

**This command automatically handles:**
- Patch regeneration from before/after files
- `FAIL_TO_PASS` auto-detection from [Test] procedures in test patch
- `PASS_TO_PASS` auto-population from the base entry
- Canonical key ordering in counterfactual.jsonl
- Problem statement directory scaffolding (copies base README **and all image/asset files** as template)

### Step 5: Edit problem statement README
- If user provided a pre-written README, copy it to the scaffolded directory at `dataset/problemstatement/<cf_instance_id>/README.md`
- Otherwise, edit the scaffolded README to describe the variant
- **Images & assets are copied automatically** by `cf-create`. Verify with `Get-ChildItem dataset/problemstatement/<cf_instance_id>/` that all referenced images are present.

### Step 6: Verify
```bash
uv run pytest tests/test_dataset_integrity.py tests/test_counterfactual.py -q
```
Confirm all tests pass. Then briefly show the created entry's key fields.

## Key Rules
- Fix patch is usually **unchanged** from base (same bug fix, different test scenario)
- If the CF requires a **different** fix, the fix/after file should contain the CF's gold fix code
- Test patch is the primary thing that changes between variants
- **No manual key reordering needed** — cf-create handles this automatically
- **No manual PASS_TO_PASS needed** — cf-create copies from base entry automatically
- Problem statement directory naming: `<base_id>__cf-N` (double underscore + hyphen)

{{{ input }}}
