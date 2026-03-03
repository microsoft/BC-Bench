# Contributing to BC-Bench

**Looking to run experiments?** Finish reading below and head over to [EXPERIMENTS.md](EXPERIMENTS.md).

## Before You Start

Please [create an issue](https://github.com/microsoft/BC-Bench/issues/new) before making significant changes. This helps us:
- Avoid duplicate work
- Discuss the approach before implementation
- Provide guidance on the codebase

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
# Folder layout
#   C:\depot\BCApps     -> cloned https://github.com/microsoft/BCApps
#   C:\depot\BC-Bench   -> this repo

gh repo clone microsoft/BC-Bench
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
uv run bcbench run copilot microsoft__BCApps-5633 --category bug-fix
```

## Development

```bash
# Run tests
uv run pytest --cov=src/bcbench --cov-report=term-missing

# Lint and format
uv run pre-commit run --all-files
```

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
