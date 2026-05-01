"""CLI commands for running agents."""

import typer
from typing_extensions import Annotated

from bcbench.agent.claude import run_claude_code
from bcbench.agent.copilot import run_copilot_agent
from bcbench.cli_options import (
    ClaudeCodeModel,
    ContainerName,
    CopilotModel,
    EvaluationCategoryOption,
    OutputDir,
    RepoPath,
)
from bcbench.config import get_config
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()

run_app = typer.Typer(help="Run agents on single dataset entry")


@run_app.command("copilot")
def run_copilot(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    container_name: ContainerName,
    model: CopilotModel = "claude-haiku-4.5",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
):
    """
    Run GitHub Copilot CLI on a single entry to generate a patch (without building/testing).

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run copilot microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps
    """
    entry = category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]
    category.pipeline.setup_workspace(entry, repo_path)

    run_copilot_agent(entry=entry, repo_path=repo_path, model=model, category=category, output_dir=output_dir, al_mcp=al_mcp, container_name=container_name)


@run_app.command("claude")
def run_claude(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    container_name: ContainerName,
    model: ClaudeCodeModel = "claude-haiku-4-5",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
):
    """
    Run Claude Code on a single entry to generate a patch (without building/testing).

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run claude microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps
    """
    entry = category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]
    category.pipeline.setup_workspace(entry, repo_path)

    run_claude_code(entry=entry, repo_path=repo_path, model=model, category=category, output_dir=output_dir, al_mcp=al_mcp, container_name=container_name)
