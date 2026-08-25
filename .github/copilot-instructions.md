# Repository: microsoft/BC-Bench

This is a benchmark for evaluating coding agents on real-world Business Central (AL) development tasks, inspired by SWE-Bench. Unlike traditional model benchmarks, BC-Bench is designed to help select models and rapidly iterate on mcp servers, custom instruction/agents, etc for engineers. The repository contains:

- **Dataset**: Benchmark entries following SWE-Bench schema with BC-specific adjustments
- **Python Package** (`src/bcbench/`): CLI tools, agent implementations, and validation utilities
- **PowerShell Scripts** (`scripts/`): Environment setup and dataset verification using AL-GO/BCContainerHelper
- **Tools** (`tools/`): Ad-hoc scripts for GitHub Artifacts download, etc
- **Agent Evaluations**: Focuses on GitHub Copilot CLI and Claude Code
- **Experiments**: MCP Servers, custom instructions, custom agents, skills, etc. and their performance on the benchmark
- **Notebooks** (`notebooks/`): Analysis and visualization of benchmark results

## Key Context
- Primary language: Python (with AL/Business Central as the target evaluation language)
- Uses `uv` for dependency management: e.g. `uv add <package>` to add packages, `uv run <command>` to run commands
- Uses `pre-commit` for code quality checks (ruff linting/formatting, trailing whitespace, etc.)

## Categories
BC-Bench is category-based and designed to grow over time. It currently has two categories, `bug-fix` and `test-generation`. They share the same dataset tasks and execution-based setup, but use different prompts, expected outputs, and evaluation pipelines. Future categories such as `code-review` can be added within the same overall benchmark structure, though they may require different inputs, setup, or evaluation methods.

## Coding Patterns and Guidelines

- Prefer strong typing and type hints
- Prefer simple code for fast iteration
- Prefer modular, testable components
- Prefer pure functions where possible
- Prefer explicit over implicit
- Prefer high-order functions like map, filter, reduce over loops
- Prefer immutable data structures where possible

### Architecture design conventions

Preserve one-way dependency flow from orchestration toward lower-level abstractions. Keep domain and result models independent of runtime code. CLI commands are composition roots: they select concrete agents and inject them into evaluation pipelines through `AgentRunner`; pipelines must not select agent implementations.

`bcbench.types` is the central category registry. Extend `EvaluationCategory` for category-owned mappings such as datasets, pipelines, results, and scoring behavior instead of duplicating those decisions elsewhere. Keep imports following the existing direction and avoid circular dependencies.

### Readable code over documentation or comments
Function names should be self-explanatory. Do NOT add docstrings to functions unless absolutely necessary.
When a docstring is necessary, keep it short and use Google style. Include only useful sections such as `Args:` and `Returns:`; skip details that are obvious from names and type hints.

Bad:
```python
def test_full_metrics_flow_to_success_result(self, sample_context):
    """Test parsing metrics, setting them on context, and creating a success result."""
```

Good:
```python
def test_full_metrics_flow_to_success_result(self, sample_context):
    # No docstring needed - the name says it all
```

### Linting and formatting
Ruff is the single source of truth (`uv run ruff check --fix`, `uv run ruff format`); config lives in `pyproject.toml`.
Lean on ruff's default rule set rather than growing `extend-select`, and prefer fixing violations over suppressing them. If a violation is genuinely intentional, use a targeted `# noqa: RULE - rationale` at that line instead of a repo-wide `ignore` entry.

## No Backward compatibility
- Do NOT worry about backward compatibility unless explicitly stated
- Do NOT worry about breaking changes

## Notebooks
- User is a software engineer, not a statistician — explain statistical concepts in plain terms
- Challenge or question statistical methods when appropriate (e.g., sample size, assumptions, alternatives)
- Prefer clear visualizations over complex statistical jargon
- Use pandas and plotly for data manipulation and visualization
