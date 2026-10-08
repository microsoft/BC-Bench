"""CLI commands for running agents."""

import logging
from typing import Annotated, cast

import typer

from bcbench.agent import BCalBackendConfig, run_bcal_agent, run_claude_code, run_copilot_agent, run_pr_review_agent
from bcbench.categories import category_definition
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
    OutputDir,
    PRReviewEnginePath,
    RepoPath,
    resolve_agent_runtime,
)
from bcbench.config import get_config
from bcbench.dataset import NL2ALEntry
from bcbench.types import EvaluationCategory

logger = logging.getLogger(__name__)
_config = get_config()

run_app = typer.Typer(help="Run agents on single dataset entry")


@run_app.command("copilot")
def run_copilot(
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
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
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
    entry = category_definition(category).load_entries(_config.paths.dataset_dir, entry_id)[0]
    category.pipeline.setup_workspace(entry, repo_path)

    run_copilot_agent(
        entry=entry,
        repo_path=repo_path,
        model=model,
        category=category,
        output_dir=output_dir,
        pass_bc_credentials=category_definition(category).pass_bc_credentials,
        runtime=runtime,
    )


@run_app.command("claude")
def run_claude(
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
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
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
    entry = category_definition(category).load_entries(_config.paths.dataset_dir, entry_id)[0]
    category.pipeline.setup_workspace(entry, repo_path)

    run_claude_code(
        entry=entry,
        repo_path=repo_path,
        model=model,
        category=category,
        output_dir=output_dir,
        pass_bc_credentials=category_definition(category).pass_bc_credentials,
        runtime=runtime,
    )


@run_app.command("pr-review")
def run_pr_review(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    model: CopilotModel = "gpt-5.6-luna",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
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
    category = EvaluationCategory.CODE_REVIEW
    entry = category_definition(category).load_entries(_config.paths.dataset_dir, entry_id)[0]
    category.pipeline.setup_workspace(entry, repo_path)

    run_pr_review_agent(
        entry=entry,
        model=model,
        repo_path=repo_path,
        category=category,
        output_dir=output_dir,
        engine_path=engine_path,
        min_severity=min_severity,
    )


@run_app.command("bcal")
def run_bcal(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    repo_path: RepoPath = _config.paths.evaluation_results_path,
    llm_command: Annotated[str | None, typer.Option(envvar="BCAL_LLM_COMMAND", help="External LLM command used by BCal")] = None,
    llm_model: Annotated[str | None, typer.Option(envvar="BCAL_LLM_MODEL", help="Optional model/deployment passed to BCal")] = None,
) -> None:
    """
    Run BCal dotnet tool on a single nl2al entry to generate AL code.

    For full evaluation, use 'bcbench evaluate bcal' instead.

    Example:
        uv run bcbench run bcal nl2al__job-budget-report-1
    """
    category = EvaluationCategory.NL2AL
    entry: NL2ALEntry = cast(NL2ALEntry, category_definition(category).load_entries(_config.paths.dataset_dir, entry_id)[0])
    category.pipeline.setup_workspace(entry, repo_path)

    run_bcal_agent(
        entry=entry,
        repo_path=repo_path,
        backend_config=BCalBackendConfig(
            command=llm_command,
            model=llm_model,
        ),
    )
