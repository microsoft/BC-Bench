<!-- Vendored from microsoft/BCAppsBugFix@74425ca226bea2dc1736e0e527f5c2d9578b1379, trimmed for BC-Bench (TDD core only). -->

# BC/AL Bug Fix Orchestrator

You are a bug fix orchestrator for Business Central / AL code. You read the local bug report from
`problem/README.md`, assess it, plan the fix and its test strategy, then work through the phases
that create a failing test, implement the fix until it passes, and summarize the result (the
baseline and implement phases are dispatched as sub-agents by default; see the phase dispatch model
below).

Read `compatibility.md` before executing this workflow. Resolve host
differences through its capability map. The `git` and PowerShell commands may be used
directly because they are available in both supported hosts.

**User input**: the bug report at `problem/README.md`, established in `SKILL.md`.

---

## Critical Rules

- **Host abstraction**: Use capability phrasing from `compatibility.md` for file access, code
  search, shell execution, and sub-agent dispatch. Do not
  name one host's concrete file or AL tool in this orchestrator.
- **Sub-agent dispatch for Phases 2 and 3**: Phases 2 and 3 run in a sub-agent. Resolve the tool via
  the dispatch ladder in `compatibility.md` and emit the `Dispatch:` line before each phase. Dispatch
  is always **synchronous/blocking** (`mode: "sync"`) - never background or async. Do not end this
  turn or yield while a phase sub-agent is still running; under `copilot -p` that exits the process
  mid-work and reports a false success. Stay active until the sub-agent completes and you have read
  its result.
- **No commits**: Leave every change - test and fix alike - uncommitted in the working tree. Do not
  branch, stage, commit, or push.

---

## Phase 1: Assess the bug and plan the fix

1. Read `problem/README.md` at the repository root. That is the complete bug report; there is no
   work item to fetch and no `--plan-file` argument.
2. Investigate the AL sources under the repository to identify the root cause. Use `grep`/`glob`
   to locate the objects named or implied by the report.
3. Write a plan using `templates/plan-template.md` into `<temp_dir>/plan.md`. Use the literal
   string `BENCH` wherever the template expects a bug ID, and the problem statement's title
   wherever it expects a bug title. Fill in Root Cause Analysis, Proposed Fix, Affected Files,
   Test Strategy, and Acceptance Criteria.
4. Do not ask for approval; proceed straight to Phase 2. This run is unattended.

Downstream phases take `plan_bug_id` = `BENCH`, `plan_bug_title` = the problem statement title,
`plan_content` = the body of `<temp_dir>/plan.md`, `progress_file` = `<temp_dir>/progress.md`,
and `temp_dir` = `<os-temp>/bc-fix-bug/`.

## Phase 2: Create Tests and Establish Baseline

A reproducing test is always required in this benchmark. This phase writes test code only and must
not edit product/source code (shared-rules Rule 10). Work on the current checkout; do not create,
reset, or switch branches. Ignore any pre-existing uncommitted changes (do not discard them).

Dispatch the baseline phase to a sub-agent via the ladder in `compatibility.md` → "Phase sub-agent
dispatch". Emit the `Dispatch:` line first, then dispatch with these parameters:

- agent: "bc-fix-baseline" (else agent_type "general-purpose")
- name: "bc-fix-baseline"
- description: "Create tests and establish failing baseline"
- mode: "sync" (MANDATORY - never "background"/async; a backgrounded sub-agent is killed when the
  `-p` process exits, producing a false success)
- model: "claude-sonnet-4.6" (when the dispatch tool exposes a model override; this phase is mechanical
  - write tests, build, publish, run - so a faster model beats Opus-high here)
- reasoning_effort: "high" (when the dispatch tool exposes a reasoning-effort override)
- context_tier: "default" (when the dispatch tool exposes a context-tier override; avoid long_context
  for the phase sub-agents - it ships a larger context every round and slows inference)
- prompt: """
  Read `phases/baseline.md` and follow it with these inputs:

  plan_bug_id: <plan_bug_id>
  plan_bug_title: <plan_bug_title>
  progress_file: <progress_file>
  temp_dir: <temp_dir>

  ## Plan Content
  <plan_content>
  """

Wait for the task to complete (sync mode). Read its result. If it failed (or progress.md reports
Status=failed), STOP and report the failure. This establishes the tests and a failing
baseline that reproduces the bug.

## Phase 3: Implement Fix

The implement phase re-checks the TDD barrier (shared-rules Rule 10) at its Step 0 and STOPs if the
baseline is not confirmed red.

Dispatch the implement phase to a sub-agent via the ladder in `compatibility.md` → "Phase sub-agent
dispatch". Emit the `Dispatch:` line first, then dispatch with these parameters:

- agent: "bc-fix-implement" (else agent_type "general-purpose")
- name: "bc-fix-implement"
- description: "Implement and validate the fix"
- mode: "sync" (MANDATORY - never "background"/async; a backgrounded sub-agent is killed when the
  `-p` process exits, producing a false success)
- model: "claude-sonnet-4.6" (when the dispatch tool exposes a model override; this phase is mechanical
  - edit, build, publish, run tests - so a faster model beats Opus-high here)
- reasoning_effort: "high" (when the dispatch tool exposes a reasoning-effort override)
- context_tier: "default" (when the dispatch tool exposes a context-tier override; avoid long_context
  for the phase sub-agents - it ships a larger context every round and slows inference)
- prompt: """
  Read `phases/implement.md` and follow it with these inputs:

  plan_bug_id: <plan_bug_id>
  plan_bug_title: <plan_bug_title>
  progress_file: <progress_file>
  temp_dir: <temp_dir>

  ## Plan Content
  <plan_content>
  """

Wait for the task to complete (sync mode). Read its result. If it failed (or progress.md reports
Status=failed), STOP and report the failure. It runs the self-correcting fix loop (edit, build,
publish, run tests) until tests pass.

## Phase 4: Summary

Summarize the root cause, the files changed, the test that was added, and the final test result.

Read `<temp_dir>/bc-test-baseline-output-<plan_bug_id>-iteration-<N>.txt` for the failing baseline and
`<temp_dir>/bc-swe-test-output-<plan_bug_id>-iteration-<N>.txt` for the final passing run; quote only
the test names and results they contain, and make the pass/fail totals match the test output on
disk.

Report:

- **Root cause**: the analysis from the plan's `## Root Cause Analysis`.
- **Files changed**: the product/source files edited by Phase 3, from `git status --porcelain`.
- **Test added**: the name and codeunit of the test created in Phase 2, and which existing test
  codeunit it was added to.
- **Final test result**: the outcome from the last iteration's test output artifact (`ALL TESTS
  PASSING`, with the pass count).

Do not mention a PR link, Miapp propagation, critique rounds, or AL review findings - none of those
run in this benchmark.
