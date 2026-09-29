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

### Documentation map

- **[CONTRIBUTING.md](CONTRIBUTING.md)** — fork setup, repo layout, versioning, day-to-day maintainer ops
- **[EXPERIMENT.md](EXPERIMENT.md)** — run an experiment (toggle instructions / skills / agents / MCP / model) against an existing category
- **[CATEGORIES.md](CATEGORIES.md)** — add a new evaluation category alongside the existing `bug-fix` / `test-generation` / `code-review` / `nl2al`

## Library and application ownership

`library/` builds the **public `bcbench-core` distribution**. It supplies typed
run identity, agent and pipeline protocols, a scoped subprocess utility, execution
steps, explicit JSONL persistence/loading, scoring, summaries and aggregation.
There are no category enums, datasets, built-in endpoints, configuration files,
credentials, publishing actions or implicit paths in the library. A consumer passes
its dataset entries, workspace, result path, pipeline, agent and scorer as Python
objects; no dataset field is interpreted as an import path. The core's only runtime
dependency is Pydantic.

The **BC-Bench repository is an application**, not the public distribution:

| Before (single `bcbench` project) | After | Owner |
| --- | --- | --- |
| `src/bcbench/evaluate/base.py` runner/template and `results/base.py` JSONL writing | Reusable `run_steps`, `AgentRunner`, `write_result` extracted into `library/src/bcbench_core/`; legacy template/result classes delegate to core | Library primitives; BC-Bench category orchestration |
| `src/bcbench/types.py`, `dataset/`, `src/bcbench/dataset/`, `src/bcbench/evaluate/{bugfix,testgeneration,codereview,...}.py` | Remain in `src/bcbench/` or `dataset/` | BC-Bench categories, schemas, prompts, fixtures, evaluation and scoring policy |
| `src/bcbench/config.py`, `cli.py`, `commands/`, `agent/shared/config.yaml`, `agent/shared/instructions/` | Remain in the application | BC-Bench CLI defaults, instruction profiles and experiment selection |
| `src/bcbench/agent/{copilot,claude,bcal,pr_review}/`, `agent/shared/mcp_gateway.py`, `collection/`, `redteam.py` | Remain in the application; no internal adapter is included in core | BC-Bench harnesses and integrations, including organization-specific CAPI and collection |
| `src/bcbench/results/{summary,leaderboard,bceval_export}.py`, `docs/_data/`, `.github/`, `scripts/` | Remain in the application | Benchmark scores, reporting, publication, CI and runner/container provisioning |
| No external example | `examples/synthetic-consumer/` | Independent synthetic consumer, not included in the core archives |

`library/pyproject.toml` is a separate build root: setuptools discovers only
`bcbench_core` under `library/src/` and excludes package data. Do **not** publish
the root `bcbench` application wheel (its metadata marks it private). The root
application depends on the local core workspace member; existing `uv run bcbench
...` workflows retain their invocations and current benchmark semantics.
The application retains its own repository-relative CLI defaults and legacy
category registry for its existing workflows; other repositories use the core
API rather than importing these BC-Bench-specific commands.

Each consuming repository must provide its **own** CI (GitHub Actions, Azure
DevOps or local), runners and environment provisioning, datasets, categories,
prompts, instruction profiles, experiment configuration, agent selection,
pipeline and scorer implementations, credential acquisition, result storage,
retention and publication. Service clients, hosts and scoped credentials belong
to the consumer; the core does not choose a provider or fall back to a public
endpoint. The BC-Bench application keeps its existing BC MCP and CAPI adapters
outside the distributable project. Agent subprocesses receive only explicitly
selected harness credentials and essential OS variables, not the entire CI
environment. Private package-feed authentication, if needed, belongs in the
consumer's installation/CI configuration, never in the core wheel or engine.
External agent CLIs, PowerShell and BC containers must be provisioned separately;
`pip install` does not provide them.

### Build and run an external consumer

From the repository root, on Python 3.13 with `uv` installed:

```sh
REPO="$(pwd -P)"
uv build --no-config "$REPO/library" --out-dir /tmp/bcbench-core-dist
uv venv --python 3.13 /tmp/bcbench-example-venv
uv pip install --python /tmp/bcbench-example-venv/bin/python /tmp/bcbench-core-dist/bcbench_core-0.1.0-py3-none-any.whl
cd /tmp
/tmp/bcbench-example-venv/bin/python "$REPO/examples/synthetic-consumer/consumer.py" \
  --dataset "$REPO/examples/synthetic-consumer/dataset.jsonl" \
  --workspace /tmp/bcbench-example-workspace \
  --output-dir /tmp/bcbench-example-output --consumer-revision example-1
```

This prints `2 answers round-tripped; mean score 1.0` and writes two per-instance
JSONL files plus `summary.jsonl` and `aggregate.jsonl` under the requested
output directory. The script has its own dataset, result model, deterministic
agent, pipeline and scorer; no core category changes are required. Run
`tar -tzf /tmp/bcbench-core-dist/bcbench-core-0.1.0.tar.gz` and
`unzip -l /tmp/bcbench-core-dist/bcbench_core-0.1.0-py3-none-any.whl` to
inspect **both** distributable archives. `tests/test_public_library.py` also
checks their allowlisted contents and executes the consumer outside the checkout.

Core run identity records the core version, consumer revision, benchmark ID,
dataset revision, scorer ID and experiment separately in each result; loading,
scoring, summarization and aggregation reject incompatible identities. BC-Bench's
legacy results also persist their application benchmark version at execution and
carry provenance through summaries, rather than computing it from today's
installation or dataset. For older result files without these fields, the
legacy summarizer still uses its original version fallback.

**Deployment decisions still required:** choose a public package registry and
versioning/release policy; do not publish automatically. A private consumer must
implement its own pipeline, credentials, data access and publication adapter.
The legacy BC-Bench CLI is intentionally still checkout-oriented; it is not a
general-purpose library CLI or a private CI integration. Core's default summary
uses a simple arithmetic mean; consumers with other scoring/aggregation policies
pass their own reducer. No automatic uploads, branch pushes, workflow dispatches
or leaderboards occur in the library.

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
