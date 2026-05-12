# Running Experiments

This document assumes you are either using the upstream repo, or you have already forked BC-Bench and completed the [setup](CONTRIBUTING.md#after-forking) (runners, secrets, dataset).

## What is an Experiment?

An experiment compares agent performance under different configurations against the same dataset. Typical examples:

- Toggling custom instructions / skills / a custom agent
- Adding an MCP server (e.g. the AL MCP) and measuring impact
- Comparing models under the same setup

The dataset, evaluation pipeline, and result format should stay constant. Only [`src/bcbench/agent/shared/config.yaml`](src/bcbench/agent/shared/config.yaml) (and the files it references) change between experiments.

## Configuring an Experiment

All configurations live in [`config.yaml`](src/bcbench/agent/shared/config.yaml):

| Setting | Default | What it does |
|---|---|---|
| `instructions.enabled` | `false` | Copy the **entire** `instructions/<owner>-<repo>/` folder (instructions + skills + agents) into the target repo before running the agent |
| `skills.enabled` | `false` | Copy **only** `instructions/<owner>-<repo>/skills/` |
| `agents.enabled` and `agents.name` | `false` | Copy **only** `instructions/<owner>-<repo>/agents/` and pass `--agent=<name>` to the CLI |
| `mcp.servers` | _(none)_ | List of MCP servers to register |

Note: `instructions.enabled: true` is a superset — you don't also need to enable `skills` or `agents` to get them. Use `skills`/`agents` when you want to isolate the effect of just that piece.

### Custom instructions / skills / custom agents

Files live under `src/bcbench/agent/shared/instructions/<owner>-<repo>/`. The folder name mirrors the dataset's repo path with `/` replaced by `-` (e.g. `microsoft/BCApps` -> `microsoft-BCApps`).

The files checked in today are **placeholders**. Replace them with whatever you want to test — your own AGENTS.md, your own skills, your own agent definitions — then toggle the corresponding flag in `config.yaml`.

```bash
instructions/
└── microsoft-BCApps/
    ├── AGENTS.md                  # renamed at runtime per agent
    ├── agents/
    │   └── ALTest.agent.md
    ├── skills/
    │   └── al-test-generation/
    │       └── SKILL.md
    └── instructions/
        ├── codeunits.instructions.md
        └── ...
```

At runtime we copy this folder into the target repo:
- **Copilot**: `<repo>/.github/` (`AGENTS.md` -> `copilot-instructions.md`)
- **Claude**: `<repo>/.claude/` (`AGENTS.md` -> `CLAUDE.md`)

## Before You Start

Articulate what you expect to see before triggering anything. A short hypothesis — *"enabling custom instructions should improve resolution rate by ~X% because…"* — makes it much easier to interpret results and decide whether a follow-up run is worth the cost.

## Running an Experiment

### 1. Land your config changes

Edit [`config.yaml`](src/bcbench/agent/shared/config.yaml), add any instruction/agent/skill files, and open a draft PR using the [template](#experiment-pr-template) below. The PR will not be merged, only serve as an entry point so people can see what exactly is being evaluated.

### 2. Smoke-test locally on a single entry

Before burning CI minutes, run one entry on your machine to confirm the config loads and the agent picks up your instructions/skills/agents:

```bash
uv run bcbench run copilot microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps
```

This only generates a patch (no build/test) and finishes in a couple of minutes.

### 3. Test run (4 entries)

Trigger the evaluation workflow from the **Actions** tab:

- **Workflow:** `Evaluation with GitHub Copilot` or `Evaluation with Claude Code`
- **`test-run`:** `true` (default — runs 4 entries, ~10 min)
- **`model`**, **`category`**, **`al-mcp`**: as needed

This catches configuration mistakes cheaply. Do not skip it.

### 4. Single full run

Once the test run passes, do one full-dataset run before committing to repeated runs:

- **`test-run`:** `false`
- **`repeat`:** `1`

Review the summary in the workflow log. If anything looks off (unexpected errors, scores far from prior baselines), investigate before spending more compute.

### 5. Repeated full runs (typically 5)

Agent runs are noisy, so a single number isn't trustworthy. For results you intend to publish or compare:

- **`test-run`:** `false`
- **`repeat`:** `5` (runs the full dataset 5 times sequentially)

Each run uploads artifacts and updates a `leaderboard/<category>/<run_id>` branch. Merge that branch to publish to the leaderboard.

### 6. Reviewing results

- The `summarize-results` job prints per-run scores in the Actions log.
- Download artifacts locally.
- For deeper analysis, see `notebooks/bug-fix/` and `notebooks/test-generation/`.

---

## Experiment PR Template

```markdown
## Experiment Description


### Configuration Changes

- [ ] Custom instructions (`instructions.enabled: true`)
- [ ] Skills (`skills.enabled: true`)
- [ ] Custom agents (`agents.enabled: true`, name: ___)
- [ ] MCP servers (list below)
- [ ] Other (describe)

### Agent & Model

- **Agent:**
- **Model:**
- **Category:**

### Hypothesis / Expected Outcome


## Notes

```
