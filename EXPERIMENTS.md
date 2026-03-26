# Running Experiments

This guide covers how to run BC-Bench evaluations with different configurations.

## Quick Start

To setup your local environment, follow [Setup](CONTRIBUTING.md) first.

## How Experiments Work

1. **You** create a PR with your experiment configuration
2. **A Microsoft reviewer** reviews the PR for correctness and safety
3. **The reviewer** triggers a test run (2 entries) to verify your setup
4. **The reviewer** triggers 5 full evaluation runs
5. **Results** are published in a results branch linked back to your PR

## Step-by-Step

### 1. Fork and create your experiment branch

```bash
# Fork the repo (one-time setup, skip if already forked)
gh repo fork microsoft/BC-Bench --clone

# Create your experiment branch
git checkout -b experiment/<meaningful-name>
```

### 2. Configure your experiment

Edit [`src/bcbench/agent/shared/config.yaml`](src/bcbench/agent/shared/config.yaml) and optionally add instruction/skill files under `src/bcbench/agent/shared/instructions/<sanitized-repo>/`.

See [Configuration Reference](#configuration-reference) below for details on each option.

> **Important:** Only modify files under `src/bcbench/agent/shared/`. Changes to other files (workflows, Python code, dataset, prompts) will not be accepted.

### 3. Test locally

Run a single entry to verify your config is picked up and function as expected.

```bash
uv run bcbench run copilot microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps
```

### 4. Open a Pull Request

Create a PR using the **Experiment** template. Fill in:
- What you're testing and your hypothesis
- Which configuration options you changed
- Which agent, model, and category to evaluate

The template includes a reviewer checklist — you don't need to fill that part in.

### 5. Wait for review and results

A Microsoft reviewer will:
1. Review your configuration changes
2. Run a test evaluation (2 entries) to verify the setup
3. Trigger 5 full evaluation runs
4. Link the results back to your PR

## Configuration Reference

### MCP Servers

Update the `mcp:` section in [config.yaml](src/bcbench/agent/shared/config.yaml), and replace the example MCP Servers with yours:

```yaml
mcp:
  servers:
    - name: "mslearn"
      type: "http"
      url: "https://learn.microsoft.com/api/mcp"
```

### Custom Instructions

Enable instructions in [config.yaml](src/bcbench/agent/shared/config.yaml):

```yaml
instructions:
  enabled: true
```

Replace the files below with your instructions:
```
src/bcbench/agent/shared/instructions/microsoft-BCApps/
  AGENTS.md
  instructions/
    tables.instructions.md
    pages.instructions.md
    codeunits.instructions.md
```

How it works (take `microsoft/BCApps` repo as example):
1. Repo name (`microsoft/BCApps`) is sanitized to `microsoft-BCApps`
2. **All files** are copied into the agent's target directory (`.github/` for Copilot, `.claude/` for Claude)
3. `AGENTS.md` is renamed to the agent-specific filename (`copilot-instructions.md` for Copilot, `CLAUDE.md` for Claude)
4. If `enabled: false`, Copilot gets `--no-custom-instructions` flag; Claude skips the file

> **Warning:** Enabling instructions copies the **entire** `instructions/<sanitized-repo>/` folder, including `skills/` and `agents/` subdirectories. If you only want custom instructions without skills or agents, remove those subdirectories from the source folder.

### Skills

Enable skills in [config.yaml](src/bcbench/agent/shared/config.yaml):

```yaml
skills:
  enabled: true
```

Replace the folder and files below with your skills:
```
src/bcbench/agent/shared/instructions/microsoft-BCApps/
  skills/
    al-test-generation/
      SKILL.md
```

How it works (take `microsoft/BCApps` repo as example):
1. Repo name (`microsoft/BCApps`) is sanitized to `microsoft-BCApps`
2. **Copilot**: The `skills/` folder is copied to `BCApps/.github/skills/` (replaces existing skills directory)
3. **Claude**: The `skills/` folder is copied to `BCApps/.claude/skills/`
4. If `enabled: false`, skills are simply not copied

### Custom Agents

Enable agents in [config.yaml](src/bcbench/agent/shared/config.yaml):

```yaml
agents:
  enabled: false
  name: ALTest
```

This controls:
1. Whether to copy custom agent files from `src/bcbench/agent/shared/instructions/<sanitized-repo>/agents/` (Copilot: `.github/agents/`, Claude: `.claude/agents/`)
2. Whether to pass `--agent=<agent-name>` to the coding agent

## Results & Metrics

Results are available in two places:
- **GitHub Actions artifacts**: per-entry result JSONL with all metrics, plus agent logs
- **Results branch**: created automatically after a successful run, can be merged to update the leaderboard

## Frequently Asked Questions

### What if some jobs fail?

Some instability is normal. The reviewer will inspect failure messages — if it's infrastructure flakiness, they'll re-queue the failed jobs. If it's a configuration issue, they'll let you know so you can update your PR.

### How long does an evaluation take?

A test run (2 entries) takes roughly 1 hour. A full run takes longer depending on the dataset size. You'll be notified on the PR when results are ready.
