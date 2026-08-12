"""CLI commands for running agents."""

from pathlib import Path
from typing import Annotated, cast

import typer

from bcbench.agent.bcal import BCalBackendConfig, run_bcal_agent
from bcbench.agent.claude import run_claude_code
from bcbench.agent.copilot import run_copilot_agent
from bcbench.agent.pr_review import run_pr_review_agent
from bcbench.cli_options import (
    ClaudeCodeModel,
    ContainerName,
    CopilotModel,
    EvaluationCategoryOption,
    OutputDir,
    RepoPath,
)
from bcbench.config import get_config
from bcbench.dataset import NL2ALEntry
from bcbench.logger import get_logger
from bcbench.types import BCalLLMBackend, EvaluationCategory

logger = get_logger(__name__)
_config = get_config()

run_app = typer.Typer(help="Run agents on single dataset entry")


def _run_pr_review(
    entry_id: str,
    model: str,
    repo_path: Path,
    output_dir: Path,
    bcquality_ref: str | None = None,
    bcquality_repo: str | None = None,
    bcquality_local_path: str | None = None,
    min_severity: str | None = None,
) -> None:
    """Generate review.json for a code-review entry via the BC-ALAgents review engine.

    Shared by 'run pr-review' and the code-review path of 'run copilot': code-review always
    runs the engine's real generate half, never a bespoke prompt. BCQuality source and
    severity default to the engine config when not overridden.
    """
    category = EvaluationCategory.CODE_REVIEW
    entry = category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]
    category.pipeline.setup_workspace(entry, repo_path)

    run_pr_review_agent(
        entry=entry,
        repo_path=repo_path,
        model=model,
        category=category,
        output_dir=output_dir,
        bcquality_ref=bcquality_ref,
        bcquality_repo=bcquality_repo,
        bcquality_local_path=bcquality_local_path,
        min_severity=min_severity,
    )


@run_app.command("copilot")
def run_copilot(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    container_name: ContainerName = "",
    model: CopilotModel = "gpt-5.6-luna",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
    al_lsp: Annotated[bool, typer.Option("--al-lsp", help="Enable AL LSP server")] = False,
) -> None:
    """
    Run GitHub Copilot CLI on a single entry to generate a patch (without building/testing).

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run copilot microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps
    """
    if category is EvaluationCategory.CODE_REVIEW:
        _run_pr_review(entry_id, model=model, repo_path=repo_path, output_dir=output_dir)
        return
    entry = category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]
    category.pipeline.setup_workspace(entry, repo_path)

    run_copilot_agent(
        entry=entry,
        repo_path=repo_path,
        model=model,
        category=category,
        output_dir=output_dir,
        al_mcp=al_mcp if container_name else False,
        al_lsp=al_lsp,
        container_name=container_name,
    )


@run_app.command("claude")
def run_claude(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    container_name: ContainerName = "",
    model: ClaudeCodeModel = "claude-haiku-4-5",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
    al_lsp: Annotated[bool, typer.Option("--al-lsp", help="Enable AL LSP server")] = False,
) -> None:
    """
    Run Claude Code on a single entry to generate a patch (without building/testing).

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run claude microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps
    """
    if category is EvaluationCategory.CODE_REVIEW:
        raise typer.BadParameter("code-review runs through BC PR Review; use 'bcbench run copilot --category code-review' or 'bcbench run pr-review'.")
    entry = category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]
    category.pipeline.setup_workspace(entry, repo_path)

    run_claude_code(
        entry=entry,
        repo_path=repo_path,
        model=model,
        category=category,
        output_dir=output_dir,
        al_mcp=al_mcp if container_name else False,
        al_lsp=al_lsp,
        container_name=container_name,
    )


@run_app.command("pr-review")
def run_pr_review(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    model: CopilotModel = "claude-sonnet-5",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    bcquality_ref: Annotated[str | None, typer.Option(help="Override the BCQuality ref (defaults to the engine's pinned ref)")] = None,
    bcquality_repo: Annotated[str | None, typer.Option(help="Override the BCQuality repo, e.g. a private fork (defaults to config/engine)")] = None,
    bcquality_local_path: Annotated[str | None, typer.Option(help="Use a local BCQuality checkout (copied + filtered, never modified) instead of fetching")] = None,
    min_severity: Annotated[str | None, typer.Option(help="AGENT_MINIMUM_SEVERITY floor (defaults to config)")] = None,
) -> None:
    """
    Run the BC-ALAgents review engine (generate half) on a single code-review entry.

    Writes review.json in the repo root without scoring. For full evaluation, use
    'bcbench evaluate pr-review' instead. Requires a local BC-ALAgents checkout
    (pr_review.path in config.yaml or BC_PR_REVIEW_ROOT), PowerShell 7+, and GH_TOKEN.

    Example:
        uv run bcbench run pr-review synthetic__style-018 --repo-path /path/to/testbed
    """
    _run_pr_review(
        entry_id,
        model=model,
        repo_path=repo_path,
        output_dir=output_dir,
        bcquality_ref=bcquality_ref,
        bcquality_repo=bcquality_repo,
        bcquality_local_path=bcquality_local_path,
        min_severity=min_severity,
    )


@run_app.command("bcal")
def run_bcal(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    repo_path: RepoPath = _config.paths.evaluation_results_path,
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
    category = EvaluationCategory.NL2AL
    entry: NL2ALEntry = cast(NL2ALEntry, category.entry_class.load(category.dataset_path, entry_id=entry_id)[0])
    category.pipeline.setup_workspace(entry, repo_path)

    run_bcal_agent(
        entry=entry,
        repo_path=repo_path,
        backend_config=BCalBackendConfig(
            backend=backend,
            endpoint=endpoint,
            deployment=deployment,
            command=llm_command,
            model=llm_model,
        ),
    )
