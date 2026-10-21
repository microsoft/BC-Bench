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

### Frozen reviewer verification experiment

The experiment branch adds `voting-phase=smoke|full` to **Evaluation with BC PR
Review** (`pr-review-evaluation.yml`). The default `off` preserves the ordinary
workflow. Voting calls `pr-review-voting.yml` and never invokes the ordinary
publisher or repeat chain. This branch is a **draft experiment PR**, not a
production rollout; do not merge it.

The frozen dataset is BC-Bench `7c98b750c200d88ed0a81daaea5e71184a3af01b`:
145 entries, 106 with expected findings, 39 empty-gold entries, 233 expected
comments and one ignored comment. A dataset hash guard rejects changes.
The smoke selects `synthetic__errh-tryfunction-swallowed-01` and
`synthetic__get-clean-01` before generation.

| Configuration | Frozen value |
|---|---|
| BC-ALAgents | `9607dea1c84fcf660983a5e3791dece1fb2f1623` |
| Inherited BCQuality | `b74967bc5b7a454eae19d6a1250199afd869f064` |
| Copilot CLI | `1.0.88` |
| Root / leaves | `gpt-5.6-sol` / `gpt-5.6-luna`, serial |
| Severity | Medium |
| Three verifiers | Independent `gpt-5.6-sol` sessions, serial within each entry |
| Semantic judge | `gpt-5.3-codex` |

Each entry uses the production `run_pr_review_agent` once. Its findings are
frozen with stable IDs. A keeps all candidates; B keeps voter1's supported
subset; C needs two explicit supported decisions. Insufficient evidence is
not refutation; invalid/missing votes exclude paired comparisons instead of
becoming negative votes. One complete candidate-to-gold same-file semantic
edge graph is judged, including ignored comments, and reused to recompute
the existing one-to-one assignment for each subset. Empty-gold cases with no
ignored comments need no judge invocation.

The **separate** smoke budget is at most 2 full reviews, 6 verifiers and 2
judge batches; the full budget is at most 145 full reviews, 435 verifiers and
106 judge batches. No invocation retries or repeat rounds are permitted.
A review itself contains multiple domain leaves/root model calls. Zero
candidates skip verification and cannot demonstrate a passing smoke.

Dispatch the existing workflow at the exact experiment commit with
`voting-phase=smoke` and `voting-revision=<that SHA>`. After inspecting a
successful smoke, dispatch **the same SHA** with `voting-phase=full`,
`voting-revision=<that SHA>`, and `voting-smoke-run=<successful run ID>`.
The workflow rejects rerun attempts, duplicate phase dispatches, revision
mismatches, and full runs without a successful same-revision smoke artifact.
The smoke requires both valid baselines, nonempty candidates, every applicable
vote/evidence resolved, correct observed model/pin identities, successful
strict scoring and A/B/C artifacts. It does not require reduced FPs or silence
on the empty-gold case. Failure stops promotion; a repair and paid retry needs
separate approval.

Each matrix job uses one Linux source checkout and the engine's declared
knowledge, with fresh voter homes, working directories and output directories.
Only `view`, `rg`, and `glob` are available; writes/shell/URLs are denied and
only the source/knowledge roots are added. Gold and other votes are outside
those roots. The verifier must perform final **exact finite range reads** in
the same context. The resolver preserves the existing conservative rules for
short, unnumbered, masked and truncated views. Omitted trailing empty quote
lines are accepted only when a complete successful view proves them explicitly,
with normalization recorded separately from semantic correctness. These are
CLI permission controls, not an OS sandbox or a guarantee against unrelated
external modifications. There are no per-voter repository copies or full-tree
hash passes.

Per-entry safe artifacts and the artifact-only aggregate are retained for
30 days, including failures, raw votes/permitted views, invocation configuration,
engine manifests, judge edges and usage. Auth homes, checkout trees and arbitrary
logs are not uploaded. Summary runs even after matrix failures and reports
selected/missing, baseline complete/scored and complete-paired populations,
micro/macro scores and unknown usage. No leaderboard, Braintrust or Kusto
publication occurs. Missing evidence remains a limitation of the experiment,
not a reason to change votes or labels after observing outcomes.

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
