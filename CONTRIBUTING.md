# Contributing to BC-Bench

Thank you for your interest in contributing to BC-Bench! This guide will help you get started with the project and experiment with different configurations.

## Quick Start

Prerequisites:
- [uv](https://docs.astral.sh/uv/)
- [GitHub CLI](https://cli.github.com/)
- [GitHub Copilot CLI](https://github.com/github/copilot-cli)

```bash
# Folder layout
#   C:\depot\NAV        -> cloned internal NAV repo
#   C:\depot\BC-Bench   -> this repo

gh repo clone microsoft/BC-Bench
cd BC-Bench

# Install python
uv python install

# Install dependencies
uv sync --all-groups

# Show CLI help
uv run bcbench --help

# Run Copilot CLI on a single entry (generate patch only, no build/test)
# This is very fast, give it a go and see it live!
uv run bcbench dataset view microsoftInternal__NAV-211710 --category bug-fix
```

## How to Experiment with GitHub Copilot CLI

By default, Copilot CLI runs with `--no-custom-instructions` and no MCP Servers (`--disable-builtin-mcps`).

Steps for an experiment:
1. Create a new branch: `git checkout -b experiment/<meaningful-name>`
2. Edit `src/bcbench/agent/copilot/config.yaml` and optionally modify instruction markdown under `src/bcbench/agent/copilot/instructions/<sanitized-repo>/` (see below)
3. Locally run one entry: `uv run bcbench run copilot <entry_id>` to ensure everything is setup correctly
4. In GitHub Actions: run workflow `copilot-evaluation` after selecting your branch & model
5. Start with **Test Run** (2 entries) → verify the changes are picked up in logs
6. Run full evaluation

> Test runs are faster (~1–2h) and help confirm MCP reachability & instruction copying before a longer full run.

### Experimenting with MCP Servers

Uncomment the `mcp:` section in [config.yaml](src/bcbench/agent/copilot/config.yaml), and replace the example MCP Servers with yours:

```yaml
mcp:
    servers:
        - name: "mslearn"
            type: "http"
            url: "https://learn.microsoft.com/api/mcp"
            tools: ["*"]
```

### Experimenting with Custom Instructions

Enable instruction in the [config.yaml](src/bcbench/agent/copilot/config.yaml):

```yaml
instructions:
  enabled: true
```

Replace the files below with your instructions:
```
src/bcbench/agent/copilot/instructions/microsoftInternal-NAV/
    copilot-instructions.md
    instructions/
        tables.instructions.md
        pages.instructions.md
        codeunits.instructions.md
```

How it works (take `NAV` repo as example):
1. Repo name (`microsoftInternal/NAV`) is sanitized to `microsoftInternal-NAV`
2. All files under `microsoftInternal-NAV` will be copied into `NAV/.github/` (overwrite if exists)
3. If `enabled: false` a `--no-custom-instructions` flag is passed instead.

### Experimenting with Custom Agents

Enable instruction in the [config.yaml](src/bcbench/agent/copilot/config.yaml):

```yaml
# controls:
# 1. whether to copy custom agents (`src/bcbench/agent/copilot/instructions/<sanitized-repo>/agents/`) into the repo
# 2. whether to pass --agent=<agent-name> to copilot
agents:
  enabled: true
  name: ALTest
```

### Results & Metrics

You can find all results in the GitHub Action (workflow: `copilot-evaluation`) directly:
- Logs: select one instance, find the step called `Run GitHub Copilot CLI ...`, and see how copilot solve an issue
- Artifacts:
    - per-entry result JSONL (with all metrics)
    - Copilot CLI logs
