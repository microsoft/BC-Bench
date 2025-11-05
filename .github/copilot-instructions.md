# Repository: microsoft/BC-Bench

This is a benchmark for evaluating AI coding agents on Business Central (AL) development tasks, inspired by SWE-Bench. The repository contains:

- **Dataset**: Benchmark entries following SWE-Bench schema with BC-specific adjustments
- **Python Package** (`src/bcbench/`): CLI tools, agent implementations, and validation utilities
- **PowerShell Scripts** (`scripts/`): Environment setup and dataset verification using AL-GO/BCContainerHelper
- **Agent Evaluations**: Focuses on mini-BC-agent (baseline), GitHub Copilot CLI, and GitHub Copilot in VS Code

**Key Context:**
- Primary language: Python (with AL/Business Central as the target evaluation language)
- Uses `uv` for dependency management
- Follows dataset schema defined in `dataset/schema.json`
- Environment configuration via `.env` file (see `.env.sample`)
- Uses `pre-commit` for code quality checks (ruff linting/formatting, trailing whitespace, etc.)

**Coding Patterns:**
- Prefer readable code over documentation
- Prefer simple code for fast iteration
- Prefer modular, testable components
