# Contributing to BC-Bench

## Contribution Model

Thank you for your interest in BC-Bench.

BC-Bench is open source, and you're welcome to fork and adapt it for your own use. We are not accepting external contributions in this repository at this time.

The instructions below are for teams that fork BC-Bench and replace the dataset with their own tasks.

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

### Dataset

Replace the dataset tasks with your own, you can keep the ones from `BCApps` as the repository is public. The tasks follow `<organization>__<repo>-<PR#number>`, the `<organization>/<repo>` by default points to GitHub repositories. If your tasks come from Azure DevOps, update the ADO branch in `scripts/BCBenchUtils.psm1` (currently hardcoded to `microsoftinternal`).

### GitHub Actions

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

## Frequently Used Operations

### Bump Coding Agent/Tool versions

Below are the steps you can follow to update coding agents' version, usually needed in scenarios like new model release.

Similar process to bump AL MCP's version, search for "Microsoft.Dynamics.BusinessCentral.Development.Tools" to identify files to modify.

1. Find the corresponding workflow file `.github/workflows/<agent-name>-evaluation.yml`
2. In the file, find the step that installs the coding agent (e.g. Install GitHub Copilot)
3. Manually change the hardcoded version (it's by design that version is hardcoded)
4. When you are done, bump BC-Bench's version in [pyproject.toml](https://github.com/microsoft/BC-Bench/blob/main/pyproject.toml#L7) following the Versioning Policy
5. Commit your changes, and merge into `main` branch
6. [Create a new release](https://github.com/microsoft/BC-Bench/releases/new)

### Add new models

You usually need to bump the coding agents' version first to be able to use the newly released model.

1. Find the corresponding workflow file `.github/workflows/<agent-name>-evaluation.yml`
2. Add the model as a new input option in the `workflow_dispatch` trigger
3. Add the model into the corresponding list in [cli_options.py](https://github.com/microsoft/BC-Bench/blob/main/src/bcbench/cli_options.py)
4. Commit your changes, and merge into `main` branch
5. Do a test run before a full one

### Create a new release

After you bump the version in [pyproject.toml](https://github.com/microsoft/BC-Bench/blob/main/pyproject.toml#L7) following the Versioning Policy, you should then [Create a new release](https://github.com/microsoft/BC-Bench/releases/new) after pushing your changes.

The process is straightforward, when you are not sure, check the previous releases for reference.

1. Create a new tag following the version in `pyproject.toml` (e.g. v1.1.2)
2. Title can simply be the same as the newly created tag
3. Describe what is changed since the last release, **only mention things that might affect evaluation result**.
