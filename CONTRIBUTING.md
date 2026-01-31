# Contributing to BC-Bench

**Looking to run experiments?** See [EXPERIMENTS.md](EXPERIMENTS.md) instead.

## Before You Start

Please [create an issue](https://github.com/microsoft/BC-Bench/issues/new) before making significant changes. This helps us:
- Avoid duplicate work
- Discuss the approach before implementation
- Provide guidance on the codebase

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

# Run Copilot CLI on a single entry (generate patch only, no build/test)
# This is very fast, give it a go and see it live!
uv run bcbench run copilot microsoft__BCApps-5633 --category bug-fix
```
