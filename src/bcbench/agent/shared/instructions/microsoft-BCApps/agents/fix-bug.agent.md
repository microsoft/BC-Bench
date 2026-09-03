---
name: fix-bug
description: >
  Fix, resolve, or patch one bug or issue in a Business Central (AL) repository.
---

# BC/AL Bug Fix

Fixes one BC/AL bug in the repository that is already checked out: investigate the root cause, plan
the change, implement it, and validate it with the AL tools when they are available.

**Scope.** The task, the repository, and the BC environment all come from the harness. This agent
does not fetch work items, does not create branches, does not commit, and does not open pull
requests. Its only output is the change in the working tree plus a short report.

## Step 1: Locate the support files and read the rules

Set `AGENT_ROOT` from the harness running this agent:

- GitHub Copilot CLI: `.github/agents/fix-bug`
- Claude Code: `.claude/agents/fix-bug`

Use only the path for the current harness; do not select it based on whether the other directory
exists, because a repository can contain configuration for both harnesses. If the expected directory
does not exist, stop and report the missing path.

Read `AGENT_ROOT/rules.md` before acting. It defines the hard constraints, how to use the AL tools,
and how to fail.

## Step 2: Extract the task

From the user prompt, identify the issue description, the repository path, and any reproduction
steps, error messages, or hints. There is no issue tracker to query and no user to ask: where the
description is incomplete, state your assumption explicitly and continue.

## Step 3: Run the workflow

Read `AGENT_ROOT/workflow.md` and execute every step of it.

## Reference files

| File | Read it when |
|---|---|
| `AGENT_ROOT/rules.md` | Always, before acting |
| `AGENT_ROOT/workflow.md` | Always, as Step 3 |
| `AGENT_ROOT/troubleshooting.md` | When a build, publish, or test call behaves in a way the workflow does not cover |
