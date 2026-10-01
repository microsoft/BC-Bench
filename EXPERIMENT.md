# Running Experiments

This document assumes you are either using the upstream repo, or you have already forked BC-Bench and completed the [setup](CONTRIBUTING.md#after-forking) (runners, secrets, dataset).

## What is an Experiment?

An experiment compares agent performance under different configurations against the **same dataset and the same category**. Typical examples:

- Toggling custom instructions / skills / a custom agent
- Adding an MCP server (e.g. the AL MCP) and measuring impact
- Comparing models under the same setup
- Comparing harness versions while keeping the model and configuration fixed

The dataset, category, evaluation pipeline, and result format stay constant. Configuration experiments change [`src/bcbench/agent/shared/config.yaml`](src/bcbench/agent/shared/config.yaml) and the files it references; harness-version comparisons change the installed CLI or engine revision instead.

> If you want to evaluate a **different kind of output** (e.g. code review instead of bug fix), that's a new category, not an experiment — see [CATEGORIES.md](CATEGORIES.md).

## Configuring an Experiment

All configurations live in [`config.yaml`](src/bcbench/agent/shared/config.yaml):

| Setting | Default | What it does |
|---|---|---|
| `instructions.enabled` | `false` | Copy the **entire** `instructions/<profile>/` folder (instructions + skills + agents) into the target repo before running the agent |
| `skills.enabled` | `false` | Copy **only** `instructions/<profile>/skills/` |
| `agents.enabled` and `agents.name` | `false` | Copy **only** `instructions/<profile>/agents/` and pass `--agent=<name>` to the CLI |
| `mcp.servers` | _(none)_ | List of MCP servers to register |
| `plugins` | _(all disabled)_ | List of agent plugins to load for the run — one entry per plugin, local or cloned from GitHub at a revision, passed to the CLI via `--plugin-dir` |

Note: `instructions.enabled: true` is a superset — you don't also need to enable `skills` or `agents` to get them. Use `skills`/`agents` when you want to isolate the effect of just that piece.

### Custom instructions / skills / custom agents

Files live under `src/bcbench/agent/shared/instructions/<profile>/`, where `<profile>` is the dataset entry's `customization_profile`. Repo-grounded categories derive it from the repo path with `/` replaced by `-` (e.g. `microsoft/BCApps` -> `microsoft-BCApps`), which reproduces the customization a developer would already have checked in. Categories that scaffold their own workspace and have no repo (e.g. `nl2al`) name their own folder and place it alongside the repo-keyed ones.

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

### Agent plugins

A [plugin](https://docs.github.com/en/copilot/concepts/agents/about-plugins) is a distributable folder bundling skills, custom agents, hooks, and MCP/LSP server configs. `plugins` is a list with **one entry per plugin**, each toggled by its own `enabled` (default `false`):

| Key | Required | What it does |
|---|---|---|
| `name` | yes | Plugin name; also how it is recorded on the result |
| `source` | yes | `local` (a folder on this machine) or `github` (cloned at runtime) |
| `path` | yes | Plugin root — an **absolute** path for `local`; relative to the clone for `github` (`"."` when the repo *is* the plugin) |
| `repo` | `github` | `owner/repo` |
| `revision` | `github` | A commit SHA (pinned) |


Entries are parsed into [`PluginConfig`](src/bcbench/types.py), and each enabled plugin is passed to the CLI as `--plugin-dir <path>` (repeatable, supported by both agents), so it is loaded for that single session only. `github` plugins are shallow-cloned with `gh repo clone` into the gitignored `<bc-bench>/.bcbench/`, deliberately outside the repo under evaluation so plugin content never reaches its diff or the agent's working directory.

Results record `ExperimentConfiguration.plugins` as `"<name>@<revision>"` / `"<name>@local"`. A `local` path is machine-specific and won't reproduce in CI, so switch to a `github` revision for a shareable run.

### Comparing harness versions

A harness-version experiment is a configuration experiment that changes a pin instead of `config.yaml`, so it follows the same process: a branch, the pin update, a BC-Bench version bump per the [versioning policy](CONTRIBUTING.md#versioning-policy), and a draft PR describing what is being evaluated. Harness pins live in [`.github/actions/install-agent-harnesses/action.yml`](.github/actions/install-agent-harnesses/action.yml). The version that actually ran is recorded on every result as `agent_version`, which keeps revisions in separate aggregates without changing `ExperimentConfiguration`.

BC PR Review additionally exposes the engine revision as a workflow input for one-off comparisons — see [Code Review](docs/code-review.md) for that harness's specifics.

### Encouraging plugin usage

Loading a plugin makes its capabilities **available** — it does not guarantee the agent **uses** them. What it takes depends on what the plugin contributes:

- **MCP servers / hooks are non-discretionary.** An MCP server's tools and a plugin's hooks are loaded every run and exercised automatically (a `SessionStart` hook can even inject context). Nothing extra is needed to test these.
- **Skills are discretionary.** The agent *sees* the loaded skills (they appear in the model's available-skills list, verified — including task-relevant ones like `systematic-debugging` for a bug-fix), but only invokes one when it judges it worthwhile. On a well-specified task (bug-fix, code-review) it typically just does the work directly and invokes nothing. So to test a **skill** plugin you must *encourage* usage.

To encourage a skill, use the **custom instructions** lever (`instructions` toggle → the repo's `AGENTS.md`): even a light nudge flips skill usage on. Append a subtle nudge like the one below to the target repo's `AGENTS.md` (under `src/bcbench/agent/shared/instructions/<profile>/`) and set `instructions.enabled: true`:

```md
## Using your skills
You have optional skills available through the `skill` tool. When you start a task, briefly consider whether one of them fits — and if it does, use it.
```

Because `instructions` is recorded on the result (`custom_instructions=True`), "plugin + nudge" is a clean, attributable experiment arm — keep the nudge subtle so you can separate the plugin's effect from the nudge's.

## Before You Start

Articulate what you expect to see before triggering anything. A short hypothesis — *"enabling custom instructions should improve resolution rate by ~X% because…"* — makes it much easier to interpret results and decide whether a follow-up run is worth the cost.

## Running an Experiment

### 1. Land your changes

Edit [`config.yaml`](src/bcbench/agent/shared/config.yaml) and add any instruction/agent/skill files, or — for a harness-version experiment — update the pin in [`.github/actions/install-agent-harnesses/action.yml`](.github/actions/install-agent-harnesses/action.yml). Then open a draft PR using the [template](#experiment-pr-template) below. The PR will not be merged, only serve as an entry point so people can see what exactly is being evaluated.

### 2. Smoke-test locally on a single entry

Before burning CI minutes, run one entry on your machine to confirm the config loads and the agent picks up your instructions/skills/agents:

```bash
uv run bcbench run copilot microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps
```

This only generates a patch (no build/test) and finishes in a couple of minutes.

### 3. Test run (4 entries)

Trigger the evaluation workflow from the **Actions** tab, selecting your experiment branch under *Use workflow from*:

- **Workflow:** `Evaluation with GitHub Copilot`, `Evaluation with Claude Code`, or `Evaluation with BC PR Review`
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

#### Copilot AL MCP diagnostics

With `--al-mcp`, Copilot evaluations first make a read-only MCP `initialize` / `tools/list` request and record the advertised tool names, including explicit `al_publish` and `al_run_tests` availability. This uses a **separate discovery process**, with the agent's server command and arguments but without its server environment or inherited credentials; it does not prove what the agent's own server advertised or what the model could see. The probe has a 30-second deadline, handles paginated catalogs, and records failures or partial discovery rather than treating them as missing tools. It never invokes tools. Known AL tool names are retained only when observed; unknown names are counted but withheld.

The safe snapshot at `<output-dir>\<run-id>\diagnostics\al-mcp.json` then tracks the agent's JSON event stream: AL server status events when emitted, AL call starts and completions, CLI success/failure flags, MCP `isError` flags when present in a recognizable result envelope, and process exit/timeout or session-error categories. An invocation is not a successful result; a successful CLI execution is not proof that publishing or tests succeeded. Missing completions remain incomplete, and missing or malformed evidence stays unknown. A tool absent from a complete observed stream is labeled `not_invoked_in_observed_stream`, not failed. Model-visible catalog and reasons for not choosing a tool are unavailable unless exposed by the runtime; no hidden reasoning is inferred. These observations are separate from the evaluator's subsequent build/publish/test steps.

Explicit error fields can also produce fixed `reported_error_markers` such as authentication, authorization, connection, timeout, compilation, or dependency. These are keyword observations, not proven causes; only the first 8 KiB per error field is inspected, and unrecognized details are withheld. Successful tool-result prose is not classified as an error.

Snapshots are atomically replaced during execution so the latest observations survive agent failure or timeout. Forced runner termination can leave an earlier snapshot with the process still marked running; artifact upload still requires the runner to reach its cleanup steps. Diagnostics do not change prompts, permissions, customizations, or scoring.

On Windows, diagnostic subprocesses enter a dedicated Job Object before execution starts, so descendants remain owned even after their parent exits. Parent exit is observed independently of stdout EOF; remaining descendants are stopped and buffered output is drained rather than waiting for the agent timeout on an inherited pipe. Cleanup is marked complete only after the job has no active processes and the I/O threads have stopped.

The Copilot workflow uploads only this projected JSON as **`al-mcp-diagnostics-<run-id>-<entry>`**, including on agent failure/timeout, with 1-day retention for test runs and 7 days for full runs. Access follows the repository's Actions artifact permissions; there is no additional destination. Diagnostic artifacts are excluded from result summarization and external result uploads. They contain no raw prompts, task/source text, arguments, tool-result text, configuration values, stderr, or CLI debug logs. Unrecognized error details are deliberately withheld rather than risking secret disclosure; do not upload raw `.log` files as a substitute.

---

## Experiment PR Template

```markdown
## Experiment Description


### Configuration Changes

- [ ] Custom instructions (`instructions.enabled: true`)
- [ ] Skills (`skills.enabled: true`)
- [ ] Custom agents (`agents.enabled: true`, name: ___)
- [ ] MCP servers (list below)
- [ ] Plugins (name + `local` path or `repo`@`revision`)
- [ ] Harness version (BC-ALAgents pin: ___, or CLI version: ___)
- [ ] Other (describe)

### Agent & Model

- **Agent:**
- **Model:**
- **Category:** <!-- bug-fix | test-generation | ... -->

### Hypothesis / Expected Outcome


## Notes

```
