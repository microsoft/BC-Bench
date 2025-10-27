"""CLI commands for evaluating agents on benchmark datasets."""

import os
import shutil
from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.agent.mini import run_mini_agent
from bcbench.dataset import DatasetEntry, load_dataset_entries
from bcbench.evaluate.evaluation_result import EvaluationResult, summarize_results
from bcbench.logger import get_logger, github_log_group
from bcbench.operations.bc_operations import build_and_publish_projects, run_tests
from bcbench.operations.git_operations import apply_patch, checkout_commit, clean_repo
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
    result = EvaluationResult(instance_id=entry_id, version=entry.environment_setup_version)

    try:
        clean_repo(repo_path)
        checkout_commit(repo_path, entry.base_commit)
        build_and_publish_projects(
            repo_path,
            entry.project_paths,
            container_name,
            username,
            password,
            entry.environment_setup_version,
        )

        with github_log_group(f"mini-bc-agent -- Entry: {entry.instance_id}"):
            run_mini_agent(
                dataset_path=DATASET_PATH,
                entry_id=entry.instance_id,
                repo_path=repo_path,
                enable_bc_tools=enable_bc_tools,
                container_name=container_name,
                username=username,
                password=password,
                step_limit=step_limit,
                cost_limit=cost_limit,
                output_dir=run_dir,
            )

        # TODO: Extract run detailed from agent (metrics to be discussed)

        apply_patch(repo_path, entry.test_patch, f"{entry.instance_id} test patch")
        build_and_publish_projects(
            repo_path,
            entry.project_paths,
            container_name,
            username,
            password,
            entry.environment_setup_version,
        )
        run_tests(entry, container_name, username, password)

        # TODO: Parse test_results to extract pass/fail counts and resolved status
        # For now, assume resolved if no exception (error will be thrown when tests fail)
        result.resolved = True

        logger.info(f"Successfully completed {entry.instance_id}")

    except Exception as e:
        result.resolved = False
        result.error_message = str(e)
        logger.error(f"Failed to process {entry.instance_id}: {e}")

    finally:
        result.save(run_dir, f"instance_results_{entry_id}.jsonl")

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
