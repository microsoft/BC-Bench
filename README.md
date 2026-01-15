# BC-Bench

[![Dataset Validation and Verification](https://github.com/microsoft/BC-Bench/actions/workflows/dataset-validation.yml/badge.svg?event=schedule)](https://github.com/microsoft/BC-Bench/actions/workflows/dataset-validation.yml) [![CI](https://github.com/microsoft/BC-Bench/actions/workflows/CI.yml/badge.svg)](https://github.com/microsoft/BC-Bench/actions/workflows/CI.yml)

A benchmark for evaluating AI coding agents on Business Central (AL) development tasks, inspired by [SWE-Bench](https://github.com/swe-bench/SWE-bench).

## Purpose

BC-Bench provides a reproducible evaluation framework for AI coding agents working on real-world Business Central development tasks. Unlike traditional model benchmarks that focus on isolated code snippets, BC-Bench evaluates agents on complete, realistic AL development scenarios.

This benchmark enables you to:
- **Measure performance** of different AI models on authentic AL issues
- **Quantify impact** of tooling changes (MCP servers, custom instructions, custom agents)
- **Track progress** with transparent, comparable metrics over time
- **Rapidly iterate** on agent configurations and evaluation setups

## Getting Started

See [CONTRIBUTING.md](CONTRIBUTING.md) for installation instructions and how to run experiments.

## Dataset

We follow the [SWE-Bench schema](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified) with BC-specific adjustments:

- `environment_setup_commit` and `version` are combined into `environment_setup_version`
- `project_paths` to enumerate AL project roots touched by the fix
- `problem_statement` and `hints_text` are not included in the jsonl file but stored under [problemstatement](/dataset/problemstatement/) for screenshots in repro steps

## Agents Under Evaluation

### mini-BC-agent (Baseline)

A minimal agent loop based on [mini-swe-agent](https://github.com/SWE-agent/mini-SWE-agent). Its simplicity makes it perfect for establishing baseline performance. See [mini-bc-agent](src/bcbench/agent/mini/agent.py).

### GitHub Copilot CLI

The [GitHub Copilot CLI](https://github.com/github/copilot-cli) (public preview Sept 2025) supports MCP servers, tools, and agent mode. It closely simulates real developers' workflow (both VS Code and Coding Agent), making it an ideal candidate for evaluating automated workflows.

## Contributing

Interested in running experiments or contributing? Check out [CONTRIBUTING.md](CONTRIBUTING.md) for detailed instructions on:
- Setting up your environment
- Running evaluations locally
- Experimenting with MCP servers, custom instructions, and custom agents
- Interpreting results and metrics
