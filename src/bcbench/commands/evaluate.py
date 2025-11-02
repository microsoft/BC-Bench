"""CLI commands for evaluating agents on benchmark datasets."""

import os
import shutil
from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.agent import run_copilot_agent, run_mini_agent
from bcbench.dataset import DatasetEntry, load_dataset_entries
from bcbench.evaluate import EvaluationContext, run_evaluation_pipeline, summarize_results
from bcbench.logger import get_logger
from bcbench.utils import DATASET_PATH, NAV_REPO_PATH

logger = get_logger(__name__)

evaluate_app = typer.Typer(help="Evaluate agents on benchmark datasets")


@evaluate_app.command("mini")
def evaluate_mini(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    container_name: Annotated[str, typer.Option(help="BC container name")],
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    repo_path: Annotated[Path, typer.Option(help="Path to NAV repository")] = NAV_REPO_PATH,
    username: Annotated[str, typer.Option(help="Username for BC container")] = "admin",
    password: Annotated[
        str | None,
        typer.Option(help="Password for BC container (or set BC_CONTAINER_PASSWORD env var)"),
    ] = None,
    step_limit: Annotated[int, typer.Option(help="Maximum number of agent steps")] = 20,
    cost_limit: Annotated[float, typer.Option(help="Maximum cost limit for agent")] = 1.0,
    output_dir: Annotated[Path, typer.Option(help="Directory to save evaluation results")] = Path("evaluation_results"),
    run_id: Annotated[str, typer.Option(help="Unique identifier for this evaluation run")] = "mini_test_run",
    enable_bc_tools: Annotated[
        bool,
        typer.Option(help="Whether to enable BC tools for the agent (build and test)"),
    ] = False,
):
    """
    Evaluate mini-bc-agent on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run mini' instead.

    Example:
        bcbench evaluate mini microsoftInternal__NAV-210528 --container-name bcserver
    """
    if not password:
        password = os.environ.get("BC_CONTAINER_PASSWORD")
        if not password:
            raise ValueError("Password required. Set password or BC_CONTAINER_PASSWORD env var")

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
    container_name: Annotated[str, typer.Option(help="BC container name")],
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    repo_path: Annotated[Path, typer.Option(help="Path to NAV repository")] = NAV_REPO_PATH,
    username: Annotated[str, typer.Option(help="Username for BC container")] = "admin",
    password: Annotated[
        str | None,
        typer.Option(help="Password for BC container (or set BC_CONTAINER_PASSWORD env var)"),
    ] = None,
    output_dir: Annotated[Path, typer.Option(help="Directory to save evaluation results")] = Path("evaluation_results"),
    run_id: Annotated[str, typer.Option(help="Unique identifier for this evaluation run")] = "copilot_test_run",
):
    """
    Evaluate GitHub Copilot CLI on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run copilot' instead.

    Example:
        bcbench evaluate copilot microsoftInternal__NAV-210528 --container-name bcserver
    """
    if not password:
        password = os.environ.get("BC_CONTAINER_PASSWORD")
        if not password:
            raise ValueError("Password required. Set password or BC_CONTAINER_PASSWORD env var")

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
        agent_name="GitHub Copilot CLI",
    )

    run_evaluation_pipeline(
        context,
        lambda ctx: run_copilot_agent(
            entry=ctx.entry,
            repo_path=ctx.repo_path,
            output_dir=ctx.result_dir,
        ),
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")


@evaluate_app.command("summarize")
def evaluate_summarize(
    run_id: Annotated[
        str,
        typer.Argument(help="Unique identifier for the evaluation run to summarize"),
    ],
    output_dir: Annotated[Path, typer.Option(help="Directory containing evaluation results")] = Path("evaluation_results"),
    result_pattern: Annotated[str, typer.Option(help="Pattern for the result files")] = "*.jsonl",
):
    """
    Summarize evaluation results from a completed run.

    Example:
        bcbench evaluate summarize mini_test_run
    """
    run_dir: Path = output_dir / run_id

    if not run_dir.exists():
        logger.error(f"Results directory not found: {run_dir}")
        raise typer.Exit(code=1)

    summarize_results(run_dir, result_pattern)
