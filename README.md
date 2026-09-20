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

The **Opt-in production bug-fix evaluation** workflow (`.github\workflows\bugfix-production-evaluation.yml`) is separate from the legacy default and keeps leaderboard updates disabled. See the [operator runbook](docs/bug-fix.md#opt-in-production-lifecycle) for setup, Copilot/Claude/replay commands, metrics, evidence, and pending promotion gates.

Both lifecycle harness commands support `--replay-patch` with optional `--replay-timeout` provenance; neither runs an agent during replay. The workflow's optional `canary-entries` JSON array selects exactly five validated IDs before provisioning. Leaving it empty preserves the existing four-entry `test-run` sample or full-dataset selection.

Use a dedicated **Windows self-hosted runner** (workflow label `GitHub-BCBench`) whose evaluator account can administer local users and ACLs, use Windows Docker, and run **BcContainerHelper 6.1.18**. **Native PowerShell 7 is required**: Store-packaged `WindowsApps` activation is not supported for contained cleanup or rehearsal. Provision Python 3.13, the locked `uv` environment, Git, Node.js 24, the selected agent harness, and the evaluator AL tools before applying restricted ACLs. The setup action pins `Microsoft.Dynamics.BusinessCentral.Development.Tools` to `18.0.37.11445-beta`, using .NET 8 for BC versions below 29 and .NET 10 otherwise; it also handles repository authentication and BC artifact setup.

Allocate a fresh entry root and a separate evaluator-only protected root for every invocation, for example `C:\bcbench\entries\<invocation>` and `C:\bcbench-protected\<invocation>`. Protected source, checkpoints, and final evidence must be outside **all agent/container mounts and mounted staging**, without links or junctions. Only the entry's `mounted-staging` area is used for checkpoint transfer; it is not protected storage. Keep the exact setup dataset inside the agent-denied benchmark checkout.

Evaluator BC credentials are `BC_SERVER_USERNAME` / `BC_SERVER_PASSWORD`; restricted credentials are `BCBENCH_LIFECYCLE_AGENT_OS_USERNAME` / `BCBENCH_LIFECYCLE_AGENT_OS_PASSWORD` and `BCBENCH_LIFECYCLE_AGENT_BC_USERNAME` / `BCBENCH_LIFECYCLE_AGENT_BC_PASSWORD`. These stay in the evaluator's environment and are not forwarded to the agent shell. Agent authentication uses `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` or `CLAUDE_CODE_OAUTH_TOKEN` (the workflow sources the latter from `secrets.ANTHROPIC_API_KEY`). **Supply secret values through environment/secret injection only, never CLI arguments, logs, or saved configuration JSON.** Setup's JSON-valued container-configuration environment variables are secret-bearing too; do not print or persist them.

Check all three quarantine locations: `<ProtectedRoot>\quarantine.json`, `<ProtectedRoot>.quarantine.json`, and `<ProtectedRoot>.cleanup-pending.quarantine.json`. Any marker blocks promotion and automatic reuse: take the runner out of service, preserve owned resources/evidence/ACLs, and inspect immutable container ownership, process shutdown, and identity security before manual containment. Cleanup attempts verified identity disablement when safe; if native contained execution is unavailable or shutdown is unverified, evidence may report identity security **unverified** and the account may remain enabled. Do not assume it was disabled, delete the markers, or force-delete the container to make a run green. Follow the [quarantine response](docs/bug-fix.md#quarantine-response).

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
