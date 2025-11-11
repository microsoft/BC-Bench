# BC-Bench

A benchmark for evaluating AI coding on Business Central (AL) development tasks, inspired by [SWE-Bench](https://github.com/swe-bench/SWE-bench).

## Repo at a glance

| Path | Purpose |
| --- | --- |
| `dataset/` | Dataset schema and benchmark entries |
| `src/bcbench/` | Python package with CLI, agent, collection, validation utilities |
| `scripts/` | PowerShell scripts for environment setup and dataset verification using AL-GO/BCContainerHelper |
| `tests/` | Tests for the CLI python package |
| `docs/` | GitHub Pages site for evaluation results |

## Quick start

### GitHub Codespaces

It's recommended to get started with [GitHub Codespaces](https://github.com/features/codespaces), its configuration is maintained [here](.devcontainer/devcontainer.json).

### Local Development

```bash
# Install gh if you don't have it: https://cli.github.com/

gh repo clone microsoft/BC-Bench
cd BC-Bench

# Install uv if you don't have it: https://docs.astral.sh/uv/

# Install all dependencies and bcbench
uv sync --all-extras
uv run bcbench --help
```

## Dataset

We follow the [SWE-Bench schema](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified) with BC-specific adjustments:

- `environment_setup_commit` and `version` are combined into `environment_setup_version`.
- `project_paths` to enumerate AL project roots touched by the fix

See full spec in [`dataset/schema.json`](./dataset/schema.json).

## What We're Evaluating

### mini-BC-agent (Baseline)

A minimal agent loop based on [mini-swe-agent](https://github.com/SWE-agent/mini-SWE-agent).

Its simplicity makes it perfect for getting things up and running and establishing baseline performance. See [mini-bc-agent](src/bcbench/agent/mini/agent.py).

### GitHub Copilot CLI

The [GitHub Copilot CLI](https://github.com/github/copilot-cli) (public preview Sept 2025) supports MCP servers, tools, and agent mode, closely simulates real developers' workflow (VSCode and Coding Agent), making it a good candidate for automated workflows.


## Contributing

This project is in early stages. Contributions, feedback, and ideas are welcome!
