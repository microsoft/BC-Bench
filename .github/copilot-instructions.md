# Repository: microsoft/BC-Bench

This is a benchmark for evaluating AI coding agents on Business Central (AL) development tasks, inspired by SWE-Bench. The repository contains:

- **Dataset**: Benchmark entries following SWE-Bench schema with BC-specific adjustments
- **Python Package** (`src/bcbench/`): CLI tools, agent implementations, and validation utilities
- **PowerShell Scripts** (`scripts/`): Environment setup and dataset verification using AL-GO/BCContainerHelper
- **Agent Evaluations**: Focuses on GitHub Copilot CLI
- **Expieriments**: Various MCP Servers, custom intructions, custom agent and their performance on the benchmark

## Key Context
- Primary language: Python (with AL/Business Central as the target evaluation language)
- Uses `uv` for dependency management: `uv add <package>` to add packages, `uv run <command>` to run commands
- Follows dataset schema defined in `dataset/schema.json`
- Uses `pre-commit` for code quality checks (ruff linting/formatting, trailing whitespace, etc.)

## Coding Patterns

- Prefer strong typing and type hints
- Prefer simple code for fast iteration
- Prefer modular, testable components
- Prefer pure functions where possible
- Prefer explicit over implicit
- Prefer high-order functions like map, filter, reduce over loops

### Readable code over documentation or comments
Test function names should be self-explanatory. Do NOT add docstrings to test functions.

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

## Backward compatibility
- Do NOT worry about backward compatibility unless explicitly stated
- Do NOT worry about breaking changes
