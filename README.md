# BC-Bench

A benchmark for evaluating AI coding on Business Central (AL) development tasks, inspired by [SWE-Bench](https://github.com/swe-bench/SWE-bench).

## Repo at a glance

| Path | Purpose |
| --- | --- |
| `dataset/` | Dataset schema and benchmark entries |
| `src/bcbench/` | Python package with CLI, agent, collection, validation utilities |
| `scripts/` | PowerShell scripts for environment setup and dataset verification using AL-GO/BCContainerHelper |

## Quick start

```bash
git clone https://github.com/microsoft/BC-Bench.git
cd BC-Bench
pip install -e ".[dev]"
python -m bcbench --help
```

### Environment Setup

Create a `.env` file in the root directory with required credentials (needed for data collection and agent runs). See [.env.sample](.env.sample) for the template.

## Dataset

We follow the [SWE-Bench schema](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified) with BC-specific adjustments:

- `environment_setup_commit` and `version` are combined into `environment_setup_version`.
- `project_paths` to enumerate AL project roots touched by the fix

See full spec in [`dataset/schema.json`](./dataset/schema.json).

## What We're Evaluating

### mini-BC-agent (Baseline)

A minimal agent loop based on [mini-swe-agent](https://github.com/SWE-agent/mini-SWE-agent). As they noted:

> Currently, top-performing systems represent a wide variety of AI scaffolds; from simple LM agent loops, to RAG systems, to multi-rollout and review type systems.

Its simplicity makes it perfect for establishing baseline performance. See [mini-BC-agent](src/bcbench/agent/mini/agent.py).

### GitHub Copilot CLI

The [GitHub Copilot CLI](https://github.com/github/copilot-cli) (public preview Sept 2025) supports MCP servers, tools, and agent mode-making it a good candidate for automated workflows.

**TODO**: Integrate and evaluate

### GitHub Copilot in VS Code

This is where AL developers actually work. Figuring out automation here is important.

**TODO**: Automate evaluation (maybe start with DevBox?)

## Contributing

This project is in early stages. Contributions, feedback, and ideas are welcome!
