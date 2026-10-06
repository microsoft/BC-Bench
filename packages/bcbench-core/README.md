# bcbench-core

Reusable, strongly typed building blocks for evaluating coding agents on Business Central (AL) tasks. [BC-Bench](https://github.com/microsoft/BC-Bench) is the first consumer; other repositories can build their own evaluation applications on top of it.

> Pre-release: not yet published. The API is being extracted from BC-Bench incrementally and may change without notice.

## Boundary

`bcbench-core` contains only genuinely reusable contracts and operations. It must not contain:

- Benchmark policy: categories, datasets, prompts, scoring thresholds, or workflows
- Repository-specific configuration, integrations, credentials, or internal material
- Python reads of global configuration or environment variables; callers pass values explicitly
- Imports of the `bcbench` application

The import and environment rules are enforced by ruff (`banned-api` in [`pyproject.toml`](pyproject.toml)); imports of undeclared dependencies are rejected by ty's `missing-direct-dependency` rule.

## Prerequisites

- `git` 2.49+ and an authenticated [GitHub CLI](https://cli.github.com/) (`gh`)
- For Copilot invocation: an installed and authenticated [GitHub Copilot CLI](https://github.com/github/copilot-cli).
- For BC container operations: PowerShell 7 with the latest [BcContainerHelper](https://github.com/microsoft/navcontainerhelper) module. The PowerShell modules ship in [`src/bcbench_core/powershell`](src/bcbench_core/powershell).

## Agent utilities

`bcbench_core.agent.copilot` provides `invoke_copilot`, `get_copilot_version`, and immutable `CopilotOptions`. Supply a prompt, model, workspace, timeout, and explicit environment; core handles launch arguments, Copilot environment settings, execution, and output parsing. Tools and custom instructions are disabled by default. Options cover logging, prepared MCP configuration, plugin directories, explicit directory grants, custom agents, and additional CLI arguments.

The moved `copilot.cli` module retains low-level CLI invocation; new session orchestration lives in `copilot.agent`. Consumers use the package-level API.

```python
from bcbench_core.agent.copilot import CopilotOptions, invoke_copilot

metrics, response = invoke_copilot(
    prompt=prompt,
    model=model,
    work_dir=workspace,
    timeout=3600,
    env=prepared_env,
    options=CopilotOptions(allow_all_tools=True, log_dir=logs, workspace_mcp=True),
)
```

`workspace_mcp=None` preserves the supplied environment setting; `True` and `False` explicitly enable or disable it. Process failures raise `CopilotProcessError` with stdout, stderr, and the exit code when available. `CopilotTimeoutError` also carries timeout metrics. Applications own prompt/tool preparation, credential policy, experiment metadata, and evaluation-specific failure handling.

`bcbench_core.agent.env.agent_subprocess_env` copies an explicit parent environment, filters caller-selected variable names and prefixes, then applies explicit overrides. Applications own the exclusion policy; the helper does not read the process environment.

## Logging

Modules log through `logging.getLogger(__name__)` and never configure logging on import. Applications call `bcbench_core.logs.setup_logging` once from their entry point.

## Development

The package is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) member of the BC-Bench repository. From the repository root:

```bash
uv sync --all-groups
uv run ruff check packages/bcbench-core
uv check --package bcbench-core --preview-features check-command
uv run pytest packages/bcbench-core
uv build --package bcbench-core
```
