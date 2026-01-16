# Contributing to BC-Bench

**Looking to run experiments?** See [EXPERIMENTS.md](EXPERIMENTS.md) instead.

## Before You Start

Please [create an issue](https://github.com/microsoft/BC-Bench/issues/new) before making significant changes. This helps us:
- Avoid duplicate work
- Discuss the approach before implementation
- Provide guidance on the codebase

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
