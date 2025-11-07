"""CLI commands for evaluating agents on benchmark datasets."""

import shutil
from pathlib import Path
from typing import Literal

import typer
from typing_extensions import Annotated

from bcbench.agent import run_copilot_agent, run_mini_agent
from bcbench.cli_options import ContainerName, ContainerPassword, ContainerUsername, CopilotModel, DatasetPath, OutputDir, RepoPath, RunId
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry, load_dataset_entries
from bcbench.evaluate import EvaluationContext, run_evaluation_pipeline
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()

evaluate_app = typer.Typer(help="Evaluate agents on benchmark datasets")


@evaluate_app.command("mini")
def evaluate_mini(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    container_name: ContainerName,
    username: ContainerUsername,
    password: ContainerPassword,
    model: Annotated[Literal["azure/gpt-4.1"], typer.Option(help="Azure AI Foundry Model to use for mini-bc-agent")] = "azure/gpt-4.1",
    dataset_path: DatasetPath = _config.paths.dataset_path,
    repo_path: RepoPath = _config.paths.nav_repo_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "mini_test_run",
    step_limit: Annotated[int, typer.Option(help="Maximum number of agent steps")] = 20,
    cost_limit: Annotated[float, typer.Option(help="Maximum cost limit for agent")] = 1.0,
    enable_bc_tools: Annotated[
        bool,
        typer.Option(help="Whether to enable BC tools for the agent (build and test)"),
    ] = False,
    include_project_paths: Annotated[
        bool,
        typer.Option(help="Whether to include project paths in the prompt"),
    ] = False,
):
    """
    Evaluate mini-bc-agent on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run mini' instead.

    Example:
        bcbench evaluate mini microsoftInternal__NAV-210528 --container-name bcserver
    """
    entries: list[DatasetEntry] = load_dataset_entries(dataset_path, entry_id=entry_id)
    entry: DatasetEntry = entries[0]
    logger.info(f"Loaded {entry_id} entry from dataset")

    run_dir: Path = output_dir / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    logger.info(f"Running evaluation on entry {entry_id} with mini-bc-agent")

    context = EvaluationContext(
        entry=entry,
        repo_path=repo_path,
        result_dir=run_dir,
        container_name=container_name,
        username=username,
        password=password,
        model=model,
        agent_name="mini-bc-agent",
        agent_options={
            "enable_bc_tools": enable_bc_tools,
            "step_limit": step_limit,
            "cost_limit": cost_limit,
        },
    )

    run_evaluation_pipeline(
        context,
        lambda ctx: run_mini_agent(
            entry=ctx.entry,
            repo_path=ctx.repo_path,
            model=ctx.model,
            include_project_paths=include_project_paths,
            enable_bc_tools=ctx.get_agent_option("enable_bc_tools", False),
            container_name=ctx.container_name,
            username=ctx.username,
            password=ctx.password,
            step_limit=ctx.get_agent_option("step_limit", 20),
            cost_limit=ctx.get_agent_option("cost_limit", 1.0),
            output_dir=ctx.result_dir,
        ),
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")


@evaluate_app.command("copilot")
def evaluate_copilot(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    container_name: ContainerName,
    username: ContainerUsername,
    password: ContainerPassword,
    model: CopilotModel = "claude-haiku-4.5",
    dataset_path: DatasetPath = _config.paths.dataset_path,
    repo_path: RepoPath = _config.paths.nav_repo_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "copilot_test_run",
    include_project_paths: Annotated[
        bool,
        typer.Option(help="Whether to include project paths in the prompt"),
    ] = False,
):
    """
    Evaluate GitHub Copilot CLI on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run copilot' instead.

    Example:
        bcbench evaluate copilot microsoftInternal__NAV-210528 --container-name bcserver
    """
    entries: list[DatasetEntry] = load_dataset_entries(dataset_path, entry_id=entry_id)
    entry: DatasetEntry = entries[0]
    logger.info(f"Loaded {entry_id} entry from dataset")

    run_dir: Path = output_dir / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    logger.info(f"Running evaluation on entry {entry_id} with GitHub Copilot CLI")

    context = EvaluationContext(
        entry=entry,
        repo_path=repo_path,
        result_dir=run_dir,
        container_name=container_name,
        username=username,
        password=password,
        model=model,
        agent_name="GitHub Copilot CLI",
    )

    run_evaluation_pipeline(
        context,
        lambda ctx: run_copilot_agent(
            entry=ctx.entry,
            repo_path=ctx.repo_path,
            model=ctx.model,
            include_project_paths=include_project_paths,
            output_dir=ctx.result_dir,
        ),
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")
