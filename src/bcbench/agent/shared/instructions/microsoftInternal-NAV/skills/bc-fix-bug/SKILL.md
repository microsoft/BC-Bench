---
name: bc-fix-bug
description: >
  Use when asked to fix, resolve, or patch a bug or issue in a Business Central (AL) repository.
  Do not use when the request is only to investigate or diagnose a bug, or when the task is to
  write or generate tests rather than fix code.
---

# BC/AL Bug Fix

Fixes one BC/AL bug in the repository that is already checked out: investigate the root cause, plan
the change, implement it, and validate it with the AL tools when they are available.

**Scope.** The task, the repository, and the BC environment all come from the harness. This skill
does not fetch work items, does not create branches, does not commit, and does not open pull
requests. Its only output is the change in the working tree plus a short report.

## Step 1: Read the rules

Read `rules.md` (next to this file) before acting. It defines the hard constraints, how to use the
AL tools, and how to fail.

## Step 2: Extract the task

From the user prompt, identify the issue description, the repository path, and any reproduction
steps, error messages, or hints. There is no issue tracker to query and no user to ask: where the
description is incomplete, state your assumption explicitly and continue.

## Step 3: Run the workflow

Read `workflow.md` and execute every step of it.

## Reference files

| File | Read it when |
|---|---|
| `rules.md` | Always, before acting |
| `workflow.md` | Always, as Step 3 |
| `troubleshooting.md` | When a build, publish, or test call behaves in a way the workflow does not cover |
