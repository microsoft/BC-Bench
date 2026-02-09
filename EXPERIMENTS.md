# Running Experiments

This guide covers how to run BC-Bench evaluations with different configurations.

## Quick Start

To setup your local environment, follow [Setup](CONTRIBUTING.md) first.

## Workflow Tips

### Check for Running Workflows

Before queueing a new run, check if there's already one running:

```bash
# List running workflows for Copilot
gh run list --workflow=copilot-evaluation --status=in_progress
```

Avoid queueing multiple full evaluations simultaneously - they compete for resources and can cause timeouts.

## Experimenting with GitHub Copilot CLI

By default, Copilot CLI runs with `--no-custom-instructions` and no MCP Servers (`--disable-builtin-mcps`).

Steps for an experiment:
1. Create a new branch: `git checkout -b experiment/<meaningful-name>`
2. Edit `src/bcbench/agent/shared/config.yaml` and optionally modify instruction markdown under `src/bcbench/agent/shared/instructions/<sanitized-repo>/` (see below)
3. Locally run one entry: `uv run bcbench run copilot <entry_id>` to ensure everything is setup correctly
4. Create a draft PR (the default template will let you switch to the experiment template)
5. In GitHub Actions: run workflow `copilot-evaluation` after selecting your branch & model
6. Start with **Test Run** (2 entries) → verify the changes are picked up in logs
7. Run full evaluation

> Test runs are faster (~1h) and help confirm MCP reachability & instruction copying before a longer full run.

## Experimenting with Claude Code

Same steps as Copilot above, but use `uv run bcbench run claude <entry_id>` locally and trigger the `claude-evaluation` workflow.

## Shared Configuration

### MCP Servers

Uncomment the `mcp:` section in [config.yaml](src/bcbench/agent/shared/config.yaml), and replace the example MCP Servers with yours:

```yaml
mcp:
  servers:
    - name: "mslearn"
      type: "http"
      url: "https://learn.microsoft.com/api/mcp"
      tools: ["*"]
```

### Custom Instructions

Enable instruction in the [config.yaml](src/bcbench/agent/shared/config.yaml):

```yaml
instructions:
  enabled: true
```

Replace the files below with your instructions:
```
src/bcbench/agent/shared/instructions/microsoftInternal-NAV/
  copilot-instructions.md
  instructions/
    tables.instructions.md
    pages.instructions.md
    codeunits.instructions.md
```

How it works (take `NAV` repo as example):
1. Repo name (`microsoftInternal/NAV`) is sanitized to `microsoftInternal-NAV`
2. **Copilot**: All files are copied into `NAV/.github/` (overwrite if exists)
3. **Claude**: All files are copied into `NAV/.claude/`
4. If `enabled: false`, Copilot gets `--no-custom-instructions` flag; Claude skips the file

### Custom Skills

Enable skills in the [config.yaml](src/bcbench/agent/shared/config.yaml):

```yaml
skills:
  enabled: true
```

Replace the folder and files below with your skills:
```
src/bcbench/agent/shared/instructions/microsoftInternal-NAV/
  skills/
    al-test-generation/
      SKILL.md
```

How it works (take `NAV` repo as example):
1. Repo name (`microsoftInternal/NAV`) is sanitized to `microsoftInternal-NAV`
2. **Copilot**: The `skills/` folder is copied to `NAV/.github/skills/` (replaces existing skills directory)
3. **Claude**: The `skills/` folder is copied to `NAV/.claude/skills/`
4. If `enabled: false`, skills are simply not copied(Copilot auto-discovers from `.github/skills/`)

### Custom Agents

Enable instruction in the [config.yaml](src/bcbench/agent/shared/config.yaml):

```yaml
# controls:
# 1. whether to copy custom agents from `src/bcbench/agent/shared/instructions/<sanitized-repo>/agents/`
#    - Copilot: copies to repo/.github/agents/
#    - Claude: copies to repo/.claude/agents/
# 2. whether to pass --agent=<agent-name> to copilot or claude
agents:
  enabled: false
  name: ALTest
```

## Results & Metrics

You can find all results in the GitHub Action (workflow: `copilot-evaluation`) directly:
- Logs: select one instance, find the step called `Run GitHub Copilot CLI ...`, and see how copilot solve an issue
- Artifacts:
  - per-entry result JSONL (with all metrics)
  - Copilot CLI logs

The workflow `claude-evaluation` follows the same procedure.
