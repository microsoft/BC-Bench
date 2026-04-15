# Repository: microsoft/BC-Bench

This is a benchmark for evaluating coding agents on real-world Business Central (AL) development tasks, inspired by SWE-Bench. Unlike traditional model benchmarks, BC-Bench is designed to help select models and rapidly iterate on mcp servers, custom instruction/agents, etc for engineers. The repository contains:

- **Dataset**: Benchmark entries following SWE-Bench schema with BC-specific adjustments
- **Python Package** (`src/bcbench/`): CLI tools, agent implementations, and validation utilities
- **PowerShell Scripts** (`scripts/`): Environment setup and dataset verification using AL-GO/BCContainerHelper
- **Tools** (`tools/`): Standalone scripts for downloading and analyzing GitHub Actions artifacts
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

### Readable code over documentation or comments
Function names should be self-explanatory. Do NOT add docstrings to functions unless absolutely necessary.

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

## No Backward compatibility
- Do NOT worry about backward compatibility unless explicitly stated
- Do NOT worry about breaking changes

## Notebooks
- User is a software engineer, not a statistician — explain statistical concepts in plain terms
- Challenge or question statistical methods when appropriate (e.g., sample size, assumptions, alternatives)
- Prefer clear visualizations over complex statistical jargon
- Use pandas and plotly for data manipulation and visualization
