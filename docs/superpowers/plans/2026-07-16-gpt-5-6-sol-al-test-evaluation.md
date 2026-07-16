# GPT-5.6 Sol AL Test Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `gpt-5.6-sol` selectable for GitHub Copilot AL test evaluations using the minimum compatible Copilot CLI harness.

**Architecture:** Keep model selection in the reusable Copilot evaluation workflow and keep harness provisioning in the shared installer action introduced by commit `eb546e4`. Add a focused regression test for those two configuration contracts, then bump the benchmark minor version because harness changes affect result comparability.

**Tech Stack:** GitHub Actions YAML, npm, Python 3.13, pytest, uv, pre-commit

---

## File Map

- Modify `.github\workflows\copilot-evaluation.yml`: expose `gpt-5.6-sol` through `workflow_dispatch`.
- Modify `.github\actions\install-eval-clis\action.yml`: pin Copilot CLI v1.0.70.
- Create `tests\test_copilot_workflow_config.py`: protect the model option and minimum harness version.
- Modify `pyproject.toml`: bump the benchmark version to 0.8.0.
- Modify `uv.lock`: keep the editable `bcbench` package version synchronized.

### Task 1: Protect the GPT-5.6 workflow contract

**Files:**
- Create: `tests\test_copilot_workflow_config.py`
- Test: `tests\test_copilot_workflow_config.py`

- [ ] **Step 1: Write the failing configuration tests**

Create `tests\test_copilot_workflow_config.py`:

```python
import re
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]


def test_copilot_workflow_exposes_gpt_5_6_sol():
    workflow = (REPO_ROOT / ".github" / "workflows" / "copilot-evaluation.yml").read_text(encoding="utf-8")

    assert '- "gpt-5.6-sol"' in workflow


def test_copilot_harness_supports_gpt_5_6():
    installer = (REPO_ROOT / ".github" / "actions" / "install-eval-clis" / "action.yml").read_text(encoding="utf-8")
    version_match = re.search(r"@github/copilot@(\d+)\.(\d+)\.(\d+)", installer)

    assert version_match is not None
    assert tuple(map(int, version_match.groups())) >= (1, 0, 70)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
uv run pytest tests\test_copilot_workflow_config.py -v
```

Expected: both tests fail because the workflow does not list `gpt-5.6-sol` and the shared installer is pinned to v1.0.57.

### Task 2: Add the model and update the harness

**Files:**
- Modify: `.github\workflows\copilot-evaluation.yml:14-25`
- Modify: `.github\actions\install-eval-clis\action.yml:11-13`
- Test: `tests\test_copilot_workflow_config.py`

- [ ] **Step 1: Add GPT-5.6 Sol to the workflow choices**

Insert the new model before the older GPT models:

```yaml
          - "claude-opus-4.8"
          - "gpt-5.6-sol"
          - "gpt-5.5"
```

Do not change the existing default model.

- [ ] **Step 2: Pin the minimum compatible Copilot CLI**

Change the shared installer step to:

```yaml
    - name: Install GitHub Copilot CLI
      run: npm install -g @github/copilot@1.0.70
      shell: pwsh
```

Do not add a release-asset fallback or self-update step.

- [ ] **Step 3: Run the configuration tests**

Run:

```powershell
uv run pytest tests\test_copilot_workflow_config.py -v
```

Expected: 2 tests pass.

- [ ] **Step 4: Commit the workflow and harness changes**

```powershell
git add .github\workflows\copilot-evaluation.yml .github\actions\install-eval-clis\action.yml tests\test_copilot_workflow_config.py
git commit -m "feat: add GPT-5.6 Sol Copilot evaluation"
```

Include the required Copilot commit trailers.

### Task 3: Bump the benchmark version

**Files:**
- Modify: `pyproject.toml:5-8`
- Modify: `uv.lock:45-48`
- Test: `tests\test_version.py`

- [ ] **Step 1: Update the project version**

Change `pyproject.toml` to:

```toml
[project]
name = "bcbench"
version = "0.8.0"
```

- [ ] **Step 2: Regenerate the lockfile**

Run:

```powershell
uv lock
```

Expected: the `bcbench` package entry in `uv.lock` changes from `0.7.1` to `0.8.0` without unrelated dependency upgrades.

- [ ] **Step 3: Verify version loading**

Run:

```powershell
uv run pytest tests\test_version.py -v
```

Expected: 2 tests pass and `get_benchmark_version()` reads the updated semantic version.

- [ ] **Step 4: Inspect the lockfile diff**

Run:

```powershell
git --no-pager diff -- pyproject.toml uv.lock
```

Expected: only the project version and editable `bcbench` lock entry change.

- [ ] **Step 5: Commit the benchmark version**

```powershell
git add pyproject.toml uv.lock
git commit -m "chore: bump benchmark version to 0.8.0"
```

Include the required Copilot commit trailers.

### Task 4: Validate harness compatibility

**Files:**
- Verify: `.github\workflows\copilot-evaluation.yml`
- Verify: `.github\actions\install-eval-clis\action.yml`
- Verify: `src\bcbench\agent\copilot\agent.py`
- Test: `tests\test_copilot_workflow_config.py`
- Test: `tests\test_copilot_metrics_parsing.py`
- Test: `tests\test_plugin_operations.py`
- Test: `tests\test_lsp_config.py`
- Test: `tests\test_agent_skills.py`
- Test: `tests\test_version.py`

- [ ] **Step 1: Confirm the npm package can be resolved**

Run:

```powershell
npm view @github/copilot@1.0.70 version
```

Expected: `1.0.70`.

- [ ] **Step 2: Run targeted compatibility tests**

Run:

```powershell
uv run pytest tests\test_copilot_workflow_config.py tests\test_copilot_metrics_parsing.py tests\test_plugin_operations.py::test_copilot_runner_records_plugins_and_sets_home tests\test_lsp_config.py tests\test_agent_skills.py tests\test_version.py -v
```

Expected: all selected tests pass.

- [ ] **Step 3: Run pre-commit on changed files**

Run:

```powershell
uv run pre-commit run --files .github\workflows\copilot-evaluation.yml .github\actions\install-eval-clis\action.yml tests\test_copilot_workflow_config.py pyproject.toml uv.lock
```

Expected: all hooks pass. If formatting changes a file, inspect the diff and rerun the same command.

- [ ] **Step 4: Verify the final diff**

Run:

```powershell
git --no-pager diff HEAD~2 -- .github\workflows\copilot-evaluation.yml .github\actions\install-eval-clis\action.yml tests\test_copilot_workflow_config.py pyproject.toml uv.lock
git status --short
```

Expected: the diff contains only the approved model option, harness pin, regression test, and benchmark version updates; the working tree is clean.
