# Running Experiments

This document assumes you are either using the upstream repo, or you have already forked BC-Bench and completed the [setup](CONTRIBUTING.md#after-forking) (runners, secrets, dataset).

## What is an Experiment?

An experiment compares agent performance under different configurations against the **same dataset and the same category**. Typical examples:

- Toggling custom instructions / skills / a custom agent
- Adding an MCP server (e.g. the AL MCP) and measuring impact
- Comparing models under the same setup

The dataset, category, evaluation pipeline, and result format stay constant. Only [`src/bcbench/agent/shared/config.yaml`](src/bcbench/agent/shared/config.yaml) (and the files it references) change between experiments.

> If you want to evaluate a **different kind of output** (e.g. code review instead of bug fix), that's a new category, not an experiment — see [CATEGORIES.md](CATEGORIES.md).

## Configuring an Experiment

All configurations live in [`config.yaml`](src/bcbench/agent/shared/config.yaml):

| Setting | Default | What it does |
|---|---|---|
| `instructions.enabled` | `false` | Copy the **entire** `instructions/<owner>-<repo>/` folder (instructions + skills + agents) into the target repo before running the agent |
| `skills.enabled` | `false` | Copy **only** `instructions/<owner>-<repo>/skills/` |
| `agents.enabled` and `agents.name` | `false` | Copy **only** `instructions/<owner>-<repo>/agents/` and pass `--agent=<name>` to the CLI |
| `mcp.servers` | _(none)_ | List of MCP servers to register |
| `plugins` | _(empty)_ | List of agent plugins to install for the run (marketplace pinned to a commit, or local). Each enabled entry is installed via the CLI's `plugin marketplace add` + `plugin install` into a per-entry isolated config home. |

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

### Marketplace & local plugins

`plugins` is a list; each entry is toggled by its own `enabled` (default `true`):

- `source: marketplace` — `repo` (`owner/repo` or git URL) + `commit` (pinned for reproducibility) + optional `path` (marketplace root within the clone, when the repo hosts the marketplace in a subdir) + `plugins` (names to install).
- `source: local` — `path` (relative to `src/bcbench/agent/shared/plugins/`, pointing at a marketplace root with `.claude-plugin/marketplace.json`) + `plugins`.

At runtime the marketplace is cloned at its commit into `<repo>/.bcbench/plugins/` and installed with the CLI's own commands into a fresh per-entry config home (`COPILOT_HOME` / `CLAUDE_CONFIG_DIR` under `.bcbench/`), which keeps parallel matrix entries isolated. A fresh home authenticates via the env token the workflow already sets (`COPILOT_GITHUB_TOKEN`; `ANTHROPIC_API_KEY`) — local plugin runs must have that token set. Installed plugins are recorded in the result's `ExperimentConfiguration.plugins` as `"<name>@<commit>"` / `"<name>@local"`.

A self-contained **example** ships at [`src/bcbench/agent/shared/plugins/bcbench-example/`](src/bcbench/agent/shared/plugins/bcbench-example/) — a minimal marketplace + plugin + skill referenced by a disabled `local` entry in `config.yaml`. Flip that entry's `enabled: true` to smoke-test the whole install path end to end (it installs into the isolated home and its skill loads; the job log shows `Installed plugin bcbench-example-plugin@bcbench-example-marketplace …`). Note: a `marketplace` source whose `marketplace.json` name is a Copilot built-in (`copilot-plugins` / `awesome-copilot`) will fail `plugin marketplace add` ("is a default marketplace") — pick a marketplace with a distinct name.

### Encouraging plugin usage

Installing a plugin makes its capabilities **available** — it does not guarantee the agent **uses** them. What it takes depends on what the plugin contributes:

- **MCP servers / hooks are non-discretionary.** An MCP server's tools and a plugin's hooks are loaded every run and exercised automatically (a `SessionStart` hook can even inject context). Nothing extra is needed to test these.
- **Skills are discretionary.** The agent *sees* installed skills (they appear in the model's available-skills list, verified — including task-relevant ones like `systematic-debugging` for a bug-fix), but only invokes one when it judges it worthwhile. On a well-specified task (bug-fix, code-review) it typically just does the work directly and invokes nothing. So to test a **skill** plugin you must *encourage* usage.

To encourage a skill, combine the `plugins` toggle with an existing lever:

1. **Custom instructions** (`instructions` toggle → the repo's `AGENTS.md`) — the reliable lever. Even a light nudge flips skill usage on. A ship-ready snippet lives at [`instructions/skill-usage-nudge.md`](src/bcbench/agent/shared/instructions/skill-usage-nudge.md): append it to the target repo's `AGENTS.md` (under `src/bcbench/agent/shared/instructions/<owner>-<repo>/`) and set `instructions.enabled: true`. Because `instructions` is recorded on the result (`custom_instructions=True`), **"plugin + nudge" is a clean, attributable experiment arm.**
2. **Category prompt** — add a general "consult your available skills" line to a category's prompt template in `config.yaml` to encourage usage across a whole category.
3. **Plugin bootstrap hook** — some plugins (e.g. `obra/superpowers`) ship a `SessionStart` hook that injects a forceful "use your skills" directive, so no nudge is needed *when it runs*. It works standalone / under Claude Code, but Copilot's headless plugin-hook execution is unreliable — don't depend on it.

Tradeoff: a nudge is itself an intervention. Keep it subtle and record it, so you can separate the plugin's effect from the nudge's.

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
- **`model`**, **`category`**, **`al-mcp`**, **`al-lsp`**: as needed

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
- **Category:** <!-- bug-fix | test-generation | ... -->

### Hypothesis / Expected Outcome


## Notes

```
