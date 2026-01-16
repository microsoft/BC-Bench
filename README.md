# BC-Bench

[![Dataset Validation and Verification](https://github.com/microsoft/BC-Bench/actions/workflows/dataset-validation.yml/badge.svg?event=schedule)](https://github.com/microsoft/BC-Bench/actions/workflows/dataset-validation.yml) [![CI](https://github.com/microsoft/BC-Bench/actions/workflows/CI.yml/badge.svg)](https://github.com/microsoft/BC-Bench/actions/workflows/CI.yml)

A benchmark for evaluating AI coding agents on Business Central (AL) development tasks, inspired by [SWE-Bench](https://github.com/swe-bench/SWE-bench).

## Purpose

BC-Bench provides a reproducible evaluation framework for AI coding agents working on real-world Business Central development tasks:

- **Measure performance** of different AI models on authentic AL issues
- **Quantify impact** of tooling changes (MCP servers, custom instructions, custom agents, etc)
- **Track progress** with transparent, comparable metrics over time
- **Rapidly iterate** on agent configurations and evaluation setups

## Dataset

We follow the [SWE-Bench schema](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified) with BC-specific adjustments:

- `environment_setup_commit` and `version` are combined into `environment_setup_version`
- `project_paths` to enumerate AL project roots touched by the fix
- `problem_statement` and `hints_text` are not included in the jsonl file but stored under [problemstatement](/dataset/problemstatement/) for screenshots in repro steps

## Agents Under Evaluation

### mini-BC-agent (Baseline)

A minimal agent loop based on [mini-swe-agent](https://github.com/SWE-agent/mini-SWE-agent). Its simplicity makes it perfect for establishing baseline performance. See [mini-bc-agent](src/bcbench/agent/mini/agent.py).

### GitHub Copilot CLI

The [GitHub Copilot CLI](https://github.com/github/copilot-cli) supports MCP servers, tools, and agent mode. It closely simulates real developers' workflow (both VS Code and Coding Agent), making it an ideal candidate for evaluating automated workflows.

## Getting Started

Ready to run experiments? See [CONTRIBUTING.md](CONTRIBUTING.md)
