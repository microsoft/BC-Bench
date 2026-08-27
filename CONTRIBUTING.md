# Contributing to BC-Bench

## Contribution Model

Thank you for your interest in BC-Bench.

BC-Bench is open source, and you're welcome to fork and adapt it for your own use. We are not accepting external contributions in this repository at this time.

This document covers both audiences:

- **Fork users** — read [Setup](#setup) and [After Forking](#after-forking).
- **Maintainers** — skip the `gh repo fork` step in [Setup](#setup), ignore [After Forking](#after-forking).

For related workflows see [EXPERIMENT.md](EXPERIMENT.md) (tweak agent setup) and [CATEGORIES.md](CATEGORIES.md) (add a new evaluation category).

## Repo Structure

A very high-level overview of the repository structure:

```
BC-Bench/
├── src/bcbench/    # Evaluation harness — agent orchestration, build/test pipeline, results
├── dataset/        # Benchmark dataset tasks
├── scripts/        # Scripts for container setup & test execution; not needed for local development
├── notebooks/      # Analysis and visualization of results
├── evaluator/      # Braintrust scorer integration, used only when uploading result to Braintrust
└── docs/           # GitHub Page for the leaderboard site
```

## Setup

Prerequisites:
- [uv](https://docs.astral.sh/uv/)
- [GitHub CLI](https://cli.github.com/)
- [GitHub Copilot CLI](https://github.com/github/copilot-cli)

```bash
# Folder layout example
#   C:\depot\BCApps     -> cloned evaluation target repository
#   C:\depot\BC-Bench   -> your fork of this repo

gh repo fork microsoft/BC-Bench --clone
cd BC-Bench

# Install python
uv python install

# Install dependencies
uv sync --all-groups

# Install pre-commit hooks
uv run pre-commit install

# Show CLI help
uv run bcbench --help

# Run Copilot CLI on a single task (generate patch only, no build/test)
# This is very fast, give it a go and see it live!
uv run bcbench run copilot microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps

# Run tests
uv run pytest --cov=src/bcbench --cov-report=term-missing

# Lint and format
uv run pre-commit run --all-files
```

## After Forking

> Fork users only. Maintainers on `microsoft/BC-Bench` can skip this section.

### Dataset

Replace the dataset tasks with your own, you can keep the ones from `BCApps` as the repository is public. The tasks follow `<organization>__<repo>-<PR#number>`, the `<organization>/<repo>` by default points to GitHub repositories. If your tasks come from Azure DevOps, update the ADO branch in `scripts/BCBenchUtils.psm1` (currently hardcoded to `microsoftinternal`).

### GitHub Actions

The upstream workflows are wired for Microsoft's internal environment. To run them on your fork:

- Replace self-hosted runner label `GitHub-BCBench` with the standard GitHub Action runners.
- Remove or update GitHub environment `ado-read`, it is used to clone from Azure DevOps.
- Set repository secrets:
  - `COPILOT_PAT` — GitHub Copilot CLI tokens
  - `ANTHROPIC_API_KEY` — Claude Code API Key
- Remove the Braintrust / bc-eval upload in `.github/workflows/summarize-results.yml`.

## Versioning Policy

BC-Bench uses [semantic versioning](https://semver.org/) to track changes that may affect evaluation results. The version is stored in `pyproject.toml` and automatically embedded in all evaluation results.

### When to Bump Versions

| Change Type | Version Bump | Examples |
|------------|--------------|----------|
| **Major** (`X.0.0`) | Dataset changes, evaluation methodology changes | Adding/removing benchmark entries, changing pass criteria |
| **Minor** (`0.X.0`) | Tooling updates that may affect results | Bumping GitHub Copilot CLI, changing agent prompts |
| **Patch** (`0.0.X`) | Bug fixes, documentation | Fixing a parsing bug, updating docs |

### Version Compatibility

Results from different benchmark versions **cannot be aggregated** together. When you run `bcbench result update`, the system will raise an error if you try to combine runs with different `benchmark_version` values.

This ensures the leaderboard always compares apples-to-apples. When bumping versions:
1. Update the version in `pyproject.toml`
2. Create a GitHub release with release notes describing the changes
3. Clear old results from `docs/_data/*.json` if needed
4. Re-run evaluations with the new version

## Maintainer Operations

> Routine tasks for maintainers working on `microsoft/BC-Bench` directly. Fork users will rarely need these unless mirroring upstream changes.

### Update an agent harness or model list

Use the repository's [`update-agent-harness` skill](.github/skills/update-agent-harness/SKILL.md) for the complete procedure. Invoke it when updating GitHub Copilot CLI, Claude Code, or their curated model choices.

The short maintainer checklist is:

1. Find the current hardcoded CLI pin in [`.github/actions/install-agent-harnesses/action.yml`](.github/actions/install-agent-harnesses/action.yml).
2. Review first-party release notes for every version between the current and target pins. Check BC-Bench's flags, authentication, non-interactive behavior, logs, and metrics parsing for breaking changes.
3. Curate models for benchmark value. Do not add every available model: prefer models that represent a new frontier, provider, capability, or cost tier, and skip older or redundant models that add little comparative value.
4. Keep model choices and defaults synchronized across `src/bcbench/cli_options.py`, evaluation workflows, command defaults, and judge configuration.
5. Bump the benchmark version in [`pyproject.toml`](pyproject.toml) according to the Versioning Policy. Harness and model-list changes normally require a minor bump.
6. Run focused compatibility tests, pre-commit, and a test evaluation with the evaluation identity before merging.

### Update a tool

Keep evaluation tools pinned so benchmark runs remain reproducible. For example, the AL MCP and LSP tooling is installed from `Microsoft.Dynamics.BusinessCentral.Development.Tools`.

1. Search for the package or executable name and identify every hardcoded pin.
2. Review first-party release notes for every intervening version, including protocol, command-line, runtime, and output changes that could affect the agent or evaluator.
3. Update all applicable pins consistently and make any required compatibility changes.
4. Run focused tests for the integration, then perform a test evaluation for tools exposed to the agent.
5. Bump the benchmark version according to the Versioning Policy. Tool changes that may affect evaluation results normally require a minor bump.

### Bump the BC PR Review engine

1. Update the pinned `microsoft/BC-ALAgents` commit in `src/bcbench/agent/shared/config.yaml`
2. Run a test evaluation through the `pr-review` workflow
3. Bump the BC-Bench version following the Versioning Policy
4. Include the exact BC-ALAgents commit SHA in the BC-Bench release notes

Comparison runs must use clean commits that can be fetched from the recorded remote. Local or dirty checkouts are for smoke tests only; a local SHA or content hash cannot recover their contents. Commit and push dependency changes before a full run.

### Create a new release

After you bump the version in [pyproject.toml](https://github.com/microsoft/BC-Bench/blob/main/pyproject.toml#L7) following the Versioning Policy, use the repository's [`create-release` skill](.github/skills/create-release/SKILL.md) to prepare release notes after pushing your changes. The skill screens merged PRs since the previous version tag and returns Markdown covering only changes that may affect evaluation results, without creating the tag or release.

1. Create a new tag following the version in `pyproject.toml` (e.g. v1.1.2)
2. Title can simply be the same as the newly created tag
3. Describe what is changed since the last release, **only mention things that might affect evaluation result**.
