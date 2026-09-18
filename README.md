# BC-Bench

[![Dataset Validation and Verification](https://github.com/microsoft/BC-Bench/actions/workflows/dataset-validation.yml/badge.svg?event=schedule)](https://github.com/microsoft/BC-Bench/actions/workflows/dataset-validation.yml) [![CI](https://github.com/microsoft/BC-Bench/actions/workflows/CI.yml/badge.svg)](https://github.com/microsoft/BC-Bench/actions/workflows/CI.yml)

A benchmark for evaluating coding agents on real-world Business Central (AL) development tasks, inspired by [SWE-Bench](https://github.com/swe-bench/SWE-bench).

## Purpose

BC-Bench provides a reproducible evaluation framework for coding agents working on real-world Business Central development tasks:

- **Measure performance** of different models on authentic AL issues
- **Quantify impact** of tooling changes (MCP servers, custom instructions, custom agents, etc)
- **Track progress** with transparent, comparable metrics over time
- **Rapidly iterate** on agent configurations and setups

## Dataset

We follow the [SWE-Bench schema](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified) with BC-specific adjustments:

- `environment_setup_commit` and `version` are combined into `environment_setup_version`
- `project_paths` to enumerate AL project roots touched by the fix
- `problem_statement` and `hints_text` are not included in the jsonl file but stored under [problemstatement](/dataset/problemstatement/) for screenshots in repro steps

## Agents Under Evaluation

### GitHub Copilot CLI

The [GitHub Copilot CLI](https://github.com/github/copilot-cli) supports MCP servers, tools, and agent mode. It closely simulates real developers' workflow (both VS Code and Coding Agent), making it an ideal candidate for evaluating automated workflows.

### Claude Code

[Claude Code](https://docs.anthropic.com/en/docs/claude-code) is Anthropic's agentic coding tool. It supports MCP servers, custom system prompts, and agent mode. BC-Bench integrates with Claude Code using the same shared configuration as Copilot.

### BC PR Review

BC PR Review is the production-fidelity BC-ALAgents + BCQuality runner for the `code-review` category. It remains separate from the category contract so its results can be compared with GitHub Copilot CLI and Claude Code on the same dataset and scorer.

## Getting Started

BC-Bench is open source, and you're welcome to fork and adapt it for your own use. We are not accepting external contributions in this repository at this time. You can run evaluations locally and replace the dataset under `dataset/` with tasks from your own codebase.

### Isolated bug-fix lifecycle

After provisioning with `scripts\Setup-BugFixLifecycle.ps1`, use `uv run bcbench bugfix-lifecycle copilot <entry>` or `claude <entry>` with the exported `BCBENCH_LIFECYCLE_*` configuration. `--replay-patch` bypasses the agent. This opt-in path is separate from normal evaluations.

Setup exports the resolved `-DatasetPath` as `BCBENCH_LIFECYCLE_DATASET_PATH` (`--dataset-path`); the CLI loads that exact file, never the category default. The file must remain inside the setup's agent-denied benchmark tree, with no links or junctions. Setup probes dataset read denial under the restricted identity; CLI validation retains that boundary and acquires cleanup ownership before validating or loading the dataset.

Both lifecycle commands parse `--output-dir` lexically and validate it after acquiring cleanup ownership. An existing file is rejected without bypassing cleanup; a malformed ownership envelope still writes raw quarantine evidence. Other commands retain their existing output-option behavior.

Production AL MCP runs in an evaluator-owned Job Object behind an unguessable loopback HTTP endpoint. BC credentials stay in evaluator-only configuration and the server environment, not the agent's MCP configuration. The isolation barrier verifies client shutdown before freezing the submission or running official phases; transport or shutdown failures fail closed. Normal nonproduction AL MCP still uses stdio.

Initialization-time server messages use the initialization response stream, including server requests that need a client reply before initialization completes. Unsolicited messages use a separate bounded event buffer (256 events) with GET reconnection and `Last-Event-ID` replay. Undelivered-event overflow, delivery deadlines, and incomplete or timed-out responses are transport failures, not empty successful responses.

If agent or bridge shutdown cannot be verified, cleanup retains owned workspaces and ACLs, disables the restricted identity, and writes quarantine evidence rather than deleting potentially active resources. Bridge shutdown failures remain terminal across repeated checks, including cleanup after failed startup.

Wrapper watchdog, nonzero-exit, and invalid-response failures retain wrapper diagnostics but do not read child capture files without verified Job Object drainage. Temporary cleanup errors cannot replace that containment-failure classification.

Production AL LSP and configured plugins are staged under the entry's setup-owned `agent-tools\plugins` directory, outside the benchmark checkout and evaluated repository. Setup grants the restricted identity read/execute access, denies modification, and records the plugin root in the exact ACL transaction. The invocation ownership marker is checked before use and cleanup. Nonproduction plugin locations are unchanged.

`tests\test_production_mcp_secrets.py` exercises real shell inspection without changing host accounts. Its `e2e` test additionally requires an explicitly provisioned disposable restricted identity and readable runtime/worker via `BCBENCH_BRIDGE_TEST_USERNAME`, `PASSWORD`, `WORKSPACE`, `PYTHON`, and `WORKER` (each with the `BCBENCH_BRIDGE_TEST_` prefix). Run it only on a dedicated runner with `uv run pytest tests\test_production_mcp_secrets.py -m e2e`; it does not provision accounts or validate a real BC server.

### Documentation map

- **[CONTRIBUTING.md](CONTRIBUTING.md)** — fork setup, repo layout, versioning, day-to-day maintainer ops
- **[EXPERIMENT.md](EXPERIMENT.md)** — run an experiment (toggle instructions / skills / agents / MCP / model) against an existing category
- **[CATEGORIES.md](CATEGORIES.md)** — add a new evaluation category alongside the existing `bug-fix` / `test-generation` / `code-review` / `nl2al`

## Citation

The [paper](https://arxiv.org/abs/2608.20851) and its [LaTeX source](paper/) describe BC-Bench's design and evaluation. If you use BC-Bench in your research, please cite:

```bibtex
@misc{sun2026bcbench,
	title={{BC-Bench}: Evaluating Agentic Engineering in a Domain-Specific Language for ERP},
	author={Sun, Haoran and Hansen, Klaus Marius},
	year={2026},
	eprint={2608.20851},
	archivePrefix={arXiv},
	primaryClass={cs.SE},
	doi={10.48550/arXiv.2608.20851},
	url={https://arxiv.org/abs/2608.20851}
}
```
