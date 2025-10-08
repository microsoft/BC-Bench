# BC-Bench AI Agent Instructions

BC-Bench is a benchmarking tool for evaluating AI coding agents on Business Central (AL) development tasks. The project is **in early stages**—keep changes simple to enable fast iteration.

## Architecture Overview

**Core Components:**
- `src/bcbench/` - Python CLI package with typer for command routing
- `dataset/` - JSONL dataset entries following `schema.json` (based on SWE-Bench)
- `scripts/powershell/` - PowerShell modules for BC container management via BCContainerHelper
- `vscode-extension/` - POC automation extension for VS Code

**Key Data Flow:**
1. **Collection**: `collect nav <PR>` → Azure DevOps PR → `DatasetEntry` → JSONL append
2. **Validation**: `validate dataset` → JSON schema check via `jsonschema` library
3. **Agent Execution**: `agent mini <instance_id>` → mini-swe-agent loop → PowerShell commands → BC container
4. **Evaluation**: PowerShell scripts run FAIL_TO_PASS tests in container to verify patches

## Critical Patterns

### Dataset Schema (dataset/schema.json)
- **BC-specific fields**: `environment_setup_version` (e.g., "25.0"), `project_paths` (AL project directories)
- **Test format**: `FAIL_TO_PASS`/`PASS_TO_PASS` use `{codeunitID, functionName[]}` not class::method
- Entries are **JSONL** (one JSON object per line, no indentation) - see `DatasetEntry.save_to_file()`

### PowerShell-First Environment
- Agent actions are PowerShell commands (see `bc_agent_config.yaml` - uses triple backticks with `powershell` language tag)
- BC-specific commands: `bc_build <path>`, `bc_test <codeunit_id> [functions]` (implemented in `BCEnvironment`)
- No persistent shell state—each command runs in new subshell (use `cd path && command` patterns)

### Lazy Imports Pattern
- mini-swe-agent imported conditionally to avoid startup message pollution (see `agent/__init__.py`, `TYPE_CHECKING` guards)
- Use `from bcbench.agent.mini_agent import ...` directly when needed, not from `__init__.py`

### Logging Configuration
- Use `get_logger(__name__)` not `logging.getLogger()` - ensures proper bcbench hierarchy
- Verbose mode via `--verbose`/`-v` flag sets bcbench loggers to DEBUG, others to WARNING
- CI environment detection: `RUNNER_DEBUG=1` or `GITHUB_ACTIONS` env vars enable debug logging

## Essential Commands

### Development Setup
```bash
pip install -e .                    # Editable install
python -m bcbench --help            # CLI entry point via __main__.py
```

### Common Workflows
```bash
# Collect dataset entry from ADO PR (requires ADO_TOKEN in .env)
bcbench collect nav 210528 --output dataset/bcbench_nav.jsonl --append

# Validate dataset against schema
bcbench validate dataset

# Run mini-agent on entry (requires BC container setup)
bcbench agent mini microsoft_Internal__NAV-210528 --repo-path /path/to/NAV --use-container
```

### Testing & Linting
```bash
# Linting with ruff (dev dependency)
ruff check src/

# No test framework yet - manual validation via CLI commands
```

## Key Files to Reference

- `src/bcbench/agent/bc_agent_config.yaml` - Agent prompt templates with PowerShell format requirements
- `src/bcbench/core/dataset_entry.py` - Dataset schema marshalling (from_json, to_dict, validate)
- `src/bcbench/agent/bc_environment.py` - Custom environment extending mini-swe-agent's LocalEnvironment
- `scripts/powershell/AppUtils.psm1` - BC container build/test helpers used by bc_build/bc_test commands

## Important Constraints

**Python 3.13+ Required** - Project uses modern Python features (see pyproject.toml)

**Windows-Centric** - BC containers run on Windows, PowerShell is primary shell (GitHub Actions workflows use `windows-latest`)

**External Dependencies:**
- Azure DevOps APIs for data collection (NAV repo)
- BCContainerHelper PowerShell module for container management
- Azure AI Foundry for LLM API calls (mini-agent)

**NAV Repository Assumption** - Dataset assumes NAV repo cloned at `BC_BENCH_ROOT.parent / "NAV"` (see `core/utils.py`)

## Quick Debugging Tips

- Check dataset entry: `python -c "from bcbench.core.dataset_entry import DatasetEntry; print(DatasetEntry.from_json({...}).to_json())"`
- View agent config: `cat src/bcbench/agent/bc_agent_config.yaml`
- Test PowerShell module: `pwsh -Command "Import-Module ./scripts/powershell/AppUtils.psm1 -Force; Get-Command -Module AppUtils"`
- Validate single entry: Create `DatasetEntry` object and call `.validate()`

## Early-Stage Notes

- No comprehensive test suite yet - focus on CLI validation
- VS Code extension is POC - automation API usage experimental
- GitHub Copilot CLI integration planned but not implemented
- Dataset is actively growing - schema may evolve (validate frequently)
