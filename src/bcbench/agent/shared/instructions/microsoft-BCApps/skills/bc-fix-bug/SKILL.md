---
name: bc-fix-bug
description: >
  Fix a single BC/AL bug test-first: read the local problem statement, plan the fix,
  create a test that reproduces the bug and fails, implement the fix until that test
  passes, and summarize. TRIGGER when the conversation asks to fix a bug or issue in
  this repository. DO NOT TRIGGER when the user only wants to investigate or diagnose
  a bug without fixing it.
allowed-tools: ['view', 'create', 'edit', 'grep', 'glob', 'powershell', 'task', 'al_build', 'al_publish', 'al_getdiagnostics', 'al_downloadsymbols', 'al_run_tests']
---

<!-- Vendored from microsoft/BCAppsBugFix@74425ca226bea2dc1736e0e527f5c2d9578b1379, trimmed for BC-Bench (TDD core only). -->

# BC/AL Bug Fix Skill

This skill fixes one BC/AL bug test-first: it reads the bug from the local problem statement,
plans the fix, creates a test that reproduces the bug and fails against the current code,
implements the fix until that test passes, and reports a summary.

This is a benchmark run, so it differs from a normal engineering workflow:

- There is **no** work item to fetch. The bug is described in `problem/README.md` at the
  repository root. Read it; do not call `gh`, `az boards`, or any network tool.
- There is **no** country-layer propagation, independent critique, AL review, or pull request.
  Stop after the fix is green and summarized.
- Do **not** commit, branch, or push. Leave all changes in the working tree.
- Write plan, progress and state files under the OS temp directory, never inside the repository.
- Target W1 localization only.
- Put the new test in the repository's existing AL test project - the one that already contains
  codeunits declaring `Subtype = Test;` - never in an application project.

The two hosts (GitHub Copilot CLI and Claude Code) expose different tools, so every phase
resolves tools through a single compatibility map. Read it first and keep it in mind throughout:

Read `compatibility.md`

When a build, publish, or test run fails in a way the phase document does not cover, consult:

Read `docs/troubleshooting.md`

## Step 1: Establish context

- Read `problem/README.md` at the repository root for the bug description and any screenshots.
- Use the repository root as `repo_root`, and `<os-temp>/bc-fix-bug/` as `temp_dir`.

## Step 2: Run the bug-fix workflow

Read and follow the full procedure in the orchestrator:

Read `orchestrator.md`

Execute every step of that procedure using the problem statement as input. The orchestrator
assesses the bug, plans the fix, creates a failing test, implements the fix, and summarizes.
