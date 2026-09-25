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
| `history.enabled` | `true` on this experiment branch | Offer task-pinned, on-demand commit history in `bug-fix` and `test-generation`; includes scope measurements |
| `history.measure_scope` | `true` on this experiment branch | Record initial/final scope without offering history, for an instrumented source-only control |

Note: `instructions.enabled: true` is a superset — you don't also need to enable `skills` or `agents` to get them. Use `skills`/`agents` when you want to isolate the effect of just that piece.

### History-assisted scope discovery

Hypothesis: after locating suspect code, historical co-changes help an agent discover related
objects worth investigating or modifying, without encouraging unnecessary changes.

Both Copilot and Claude support this experiment. It is restricted to `bug-fix` and
`test-generation`; other categories ignore these settings. This experiment branch enables
both flags in `config.yaml`. Setting both to `false` restores the original prompt/tool
setup. No assertion checks or pass/fail criteria are changed.

Use this instrumented source-only control:

```yaml
history:
  enabled: false
  measure_scope: true
  max_commits: 5
  max_files: 10
  history_depth: 200
  max_requests: 5
```

For the history arm, change only `enabled` to `true`. History automatically enables scope
measurement. Keep the task set, model, harness version, other tools, and limits identical.
Run the normal `bcbench run` or `bcbench evaluate` command; there is no separate history CLI
flag. Configuration, including all limits and the control/history distinction, is recorded
in `ExperimentConfiguration.history` and separates result aggregates.

The harness starts a localhost MCP capability named `history`:

1. The agent investigates current source and calls `record_scope(stage="initial", files=...,
   note=...)` before editing or requesting history. No suspect file names are prefilled.
2. In the history arm only, `get_history(files=...)` retrieves bounded historical changes.
   The agent cannot supply a repository, cutoff, output location, or limits: the harness
   pins these from the dataset entry and experiment settings.
3. The agent follows relevant leads in current source and records its final scope with
   `record_scope(stage="final", files=..., note=...)` before finishing.

The initial snapshot cannot be rewritten after seeing history. Later history requests
invalidate an earlier final snapshot until it is recorded again. A failed history request
is reported to the agent and recorded as an error, not as an empty successful query. The
source-only control exposes scope recording but no history retrieval. Both instrumented
prompts prohibit alternative Git/web history lookups; this instruction is not a replacement
for network/process isolation if hard enforcement is required.

Reports retain every changed path but display only the configured number of distinct
modified filenames per commit. Localization copies share a filename slot. Added, deleted,
and renamed/moved files are listed without content. The standalone utility and exact
authentication/history semantics are documented in [tools/README.md](tools/README.md).

The automatic capability queries only the task's repository. It never invents a second
repository's cutoff or uses the current BCAppsBugFix checkout as a historical boundary.
NAV requires a runner identity with NAV read access. The evaluation workflows reuse the
existing `ado-read` environment's Azure client/tenant secrets and `id-token: write`
permission to obtain a fresh ADO token through GitHub OIDC for each history request.
They do not depend on the setup action's step-local `ADO_TOKEN` or an aging Azure CLI
federated assertion. Local use still supports `ADO_TOKEN`, a read-scoped
`AZURE_DEVOPS_EXT_PAT`, or an authenticated Azure CLI session. BCApps uses public access
or the configured GitHub token. Runtime token headers are held by the report runner, not the MCP tool
arguments/configuration. No network query or Markdown report is generated at agent startup.

#### Measurements and interpretation

Per-instance JSONL results contain an optional `investigation` object with:

- Initial/final **agent-reported** file scope and brief notes, not proof of actual file reads.
- Added scope files, history-query inputs, returned commit IDs, report names, durations,
  and explicit errors.
- Reference source-file recall before/after, recall gain, and newly identified reference files.
- Files actually changed by the candidate patch and changes outside the reference output's
  file set. These are observations, not automatic correctness penalties.

Reference comparisons happen in the trusted result layer **after the agent finishes**.
Gold patches and reference file names are never passed to the history capability. Scope
recall uses the gold production fix's files for both categories. Actual changed-file
comparisons use the gold production patch for bug-fix and the gold test patch for
test-generation. Comparisons normalize separators and case, but remain file-based proxies,
not semantic AL-object identity or an exhaustive definition of relevant scope.

Keep the test-generation input mode fixed between arms. In `both` and `gold-patch` modes,
the fix is already visible, so initial reference-file recall may already be perfect.
Use `problem-statement` mode when specifically testing discovery without seeing the fix;
do not interpret a zero recall gain in a fix-visible task as proof that history was unused.

Missing initial/final snapshots remain unavailable, not zero. Summaries show completeness,
query/error counts and time, and before/after reference recall over the **same complete
pairs**. Multi-run aggregates weight by measured attempt counts rather than averaging
averages. Scalar measurements are also included in bc-eval metadata with `scope_` and
`history_` prefixes. Existing resolution, build, latency, token and cost metrics remain
available for comparing outcomes and overhead.

Check the multi-file reference subset separately (`scope_reference_source_files > 1`), but
retain all tasks to identify regressions. Additional files outside the gold patch may be
legitimate; review their relevance rather than treating reference overlap as a new score.

Reports are saved beneath the run directory's `history/` folder. The existing workflow
uploads result JSONL, not these raw reports. Keep NAV history and any transcripts containing
it out of public artifacts/logs; use access-controlled storage if retaining full reports.

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
