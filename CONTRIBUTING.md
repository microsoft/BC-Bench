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

```bash
gh repo clone microsoft/BC-Bench
cd BC-Bench

uv python install
uv sync --all-groups

# Install pre-commit hooks
uv run pre-commit install
```
