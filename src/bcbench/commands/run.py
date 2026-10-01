"""CLI commands for running agents."""

from pathlib import Path
from typing import Annotated, cast

import typer

from bcbench.application import AgentSelection, EvaluationRequest, run_entry
from bcbench.cli_options import (
    ClaudeCodeModel,
    ContainerCompany,
    ContainerMcpUrl,
    ContainerName,
    ContainerPassword,
    ContainerServerInstance,
    ContainerServerUrl,
    ContainerUsername,
    CopilotModel,
    EvaluationCategoryOption,
    PRReviewEnginePath,
    resolve_agent_runtime,
)
from bcbench.commands.composition import build_category_registry, command_context, select_agent
from bcbench.logger import get_logger
from bcbench.types import AgentHarness, BCalLLMBackend, EvaluationCategory

logger = get_logger(__name__)

run_app = typer.Typer(help="Run agents on single dataset entry")


@run_app.command("copilot")
def run_copilot(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    container_name: ContainerName = "",
    username: ContainerUsername = "",
    password: ContainerPassword = "",
    server_url: ContainerServerUrl = "",
    server_instance: ContainerServerInstance = "",
    mcp_url: ContainerMcpUrl = None,
    company: ContainerCompany = "",
    model: CopilotModel = "gpt-5.6-luna",
    repo_path: Annotated[Path | None, typer.Option(help="Path to repository")] = None,
    output_dir: Annotated[Path | None, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)] = None,
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
    al_lsp: Annotated[bool, typer.Option("--al-lsp", help="Enable AL LSP server")] = False,
    bc_mcp: Annotated[bool, typer.Option("--bc-mcp", help="Enable the Business Central MCP server")] = False,
) -> None:
    """
    Run GitHub Copilot CLI on a single entry to generate the category output.

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run copilot microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps
    """
    runtime = resolve_agent_runtime(
        container_name=container_name,
        username=username,
        container_password=password,
        server_url=server_url,
        server_instance=server_instance,
        mcp_url=mcp_url,
        company=company,
        al_mcp=al_mcp,
        al_lsp=al_lsp,
        bc_mcp=bc_mcp,
    )
    state = command_context(ctx)
    definition = build_category_registry(state)[category]
    run_entry(
        definition,
        EvaluationRequest(
            entry_id=entry_id,
            repo_path=repo_path or state.config.paths.testbed_path,
            output_dir=output_dir or state.config.paths.evaluation_results_path,
            container=runtime.container if runtime else None,
        ),
        select_agent(state, definition, name=AgentHarness.COPILOT, model=model, runtime=runtime, evaluate=False),
    )


@run_app.command("claude")
def run_claude(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    container_name: ContainerName = "",
    username: ContainerUsername = "",
    password: ContainerPassword = "",
    server_url: ContainerServerUrl = "",
    server_instance: ContainerServerInstance = "",
    mcp_url: ContainerMcpUrl = None,
    company: ContainerCompany = "",
    model: ClaudeCodeModel = "claude-haiku-4-5",
    repo_path: Annotated[Path | None, typer.Option(help="Path to repository")] = None,
    output_dir: Annotated[Path | None, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)] = None,
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
    al_lsp: Annotated[bool, typer.Option("--al-lsp", help="Enable AL LSP server")] = False,
    bc_mcp: Annotated[bool, typer.Option("--bc-mcp", help="Enable the Business Central MCP server")] = False,
) -> None:
    """
    Run Claude Code on a single entry to generate the category output.

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run claude microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps
    """
    runtime = resolve_agent_runtime(
        container_name=container_name,
        username=username,
        container_password=password,
        server_url=server_url,
        server_instance=server_instance,
        mcp_url=mcp_url,
        company=company,
        al_mcp=al_mcp,
        al_lsp=al_lsp,
        bc_mcp=bc_mcp,
    )
    state = command_context(ctx)
    definition = build_category_registry(state)[category]
    run_entry(
        definition,
        EvaluationRequest(
            entry_id=entry_id,
            repo_path=repo_path or state.config.paths.testbed_path,
            output_dir=output_dir or state.config.paths.evaluation_results_path,
            container=runtime.container if runtime else None,
        ),
        select_agent(state, definition, name=AgentHarness.CLAUDE, model=model, runtime=runtime, evaluate=False),
    )


@run_app.command("pr-review")
def run_pr_review(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    model: CopilotModel = "gpt-5.6-luna",
    repo_path: Annotated[Path | None, typer.Option(help="Path to repository")] = None,
    output_dir: Annotated[Path | None, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)] = None,
    engine_path: PRReviewEnginePath = None,
    min_severity: Annotated[str | None, typer.Option(help="AGENT_MINIMUM_SEVERITY floor (defaults to config)")] = None,
) -> None:
    """
    Run BC PR Review on a single code-review entry.

    This production-fidelity runner is fixed to the code-review category, while the same
    category can also run through the generic copilot and claude commands for cross-system
    comparison. Writes review.json without scoring; for full evaluation use
    'bcbench evaluate pr-review'. Requires a local BC-ALAgents checkout
    (--engine-path or BC_PR_REVIEW_ROOT), PowerShell 7+, and an authenticated
    Copilot CLI.

    Example:
        uv run bcbench run pr-review synthetic__style-018 --repo-path /path/to/testbed
    """
    state = command_context(ctx)
    definition = build_category_registry(state)[EvaluationCategory.CODE_REVIEW]
    run_entry(
        definition,
        EvaluationRequest(
            entry_id=entry_id,
            repo_path=repo_path or state.config.paths.testbed_path,
            output_dir=output_dir or state.config.paths.evaluation_results_path,
        ),
        select_agent(state, definition, name=AgentHarness.PR_REVIEW, model=model, runtime=None, evaluate=False, engine_path=engine_path, min_severity=min_severity),
    )


@run_app.command("bcal")
def run_bcal(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    repo_path: Annotated[Path | None, typer.Option(help="Path to repository")] = None,
    backend: Annotated[BCalLLMBackend, typer.Option(envvar="BCAL_LLM_BACKEND", help="BCal LLM backend to use")] = BCalLLMBackend.AZURE_OPENAI,
    endpoint: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_ENDPOINT", help="Azure OpenAI endpoint (required for azure-openai backend)")] = None,
    deployment: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_DEPLOYMENT", help="Azure OpenAI deployment (required for azure-openai backend)")] = None,
    llm_command: Annotated[str | None, typer.Option(envvar="BCAL_LLM_COMMAND", help="LLM command (required for external-command backend)")] = None,
    llm_model: Annotated[str | None, typer.Option(envvar="BCAL_LLM_MODEL", help="LLM model/deployment (optional for external-command backend)")] = None,
) -> None:
    """
    Run BCal dotnet tool on a single nl2al entry to generate AL code.

    For full evaluation, use 'bcbench evaluate bcal' instead.

    Example:
        uv run bcbench run bcal nl2al__job-budget-report-1
    """
    from bcbench.agent.bcal import BCalBackendConfig, run_bcal_agent
    from bcbench.dataset import NL2ALEntry

    state = command_context(ctx)
    definition = build_category_registry(state)[EvaluationCategory.NL2AL]
    backend_config = BCalBackendConfig(backend=backend, endpoint=endpoint, deployment=deployment, command=llm_command, model=llm_model)
    run_entry(
        definition,
        EvaluationRequest(
            entry_id=entry_id,
            repo_path=repo_path or state.config.paths.evaluation_results_path,
            output_dir=state.config.paths.evaluation_results_path,
        ),
        AgentSelection(
            name=AgentHarness.BCAL,
            model=backend_config.model_label(),
            runner=lambda context: run_bcal_agent(entry=cast(NL2ALEntry, context.entry), repo_path=context.repo_path, backend_config=backend_config),
        ),
    )
