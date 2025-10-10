"""CLI commands for evaluating agents on benchmark datasets."""

import os
import shutil
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

from bcbench.core.utils import DATASET_PATH, NAV_REPO_PATH
from bcbench.core.logger import get_logger, github_log_group
from bcbench.core.git_operations import clean_repo, checkout_commit, apply_patch
from bcbench.core.bc_operations import build_and_publish_projects, run_tests
from bcbench.dataset import load_dataset_entries, DatasetEntry
from bcbench.agent.mini import run_mini_agent
from bcbench.evaluate.evaluation_result import EvaluationResult, summarize_results

logger = get_logger(__name__)

evaluate_app = typer.Typer(help="Evaluate agents on benchmark datasets")


@evaluate_app.command("mini")
def evaluate_mini(
    version: Annotated[str, typer.Argument(help="Environment setup version to evaluate")],
    container_name: Annotated[str, typer.Option(help="BC container name")],
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    repo_path: Annotated[Path, typer.Option(help="Path to NAV repository")] = NAV_REPO_PATH,
    username: Annotated[str, typer.Option(help="Username for BC container")] = "admin",
    password: Annotated[Optional[str], typer.Option(help="Password for BC container (or set BC_CONTAINER_PASSWORD env var)")] = None,
    step_limit: Annotated[int, typer.Option(help="Maximum number of agent steps")] = 20,
    cost_limit: Annotated[float, typer.Option(help="Maximum cost limit for agent")] = 1.0,
    output_dir: Annotated[Path, typer.Option(help="Directory to save evaluation results")] = Path("evaluation_results"),
    run_id: Annotated[str, typer.Option(help="Unique identifier for this evaluation run")] = "mini_test_run",
    enable_bc_tools: Annotated[bool, typer.Option(help="Whether to enable BC tools for mini agent (build and test)")] = False,
):
    """
    Evaluate mini-bc-agent on all entries for a specific version.

    Example:
        bcbench evaluate mini 28.0 --container-name bcserver
    """
    if not password:
        password = os.environ.get("BC_CONTAINER_PASSWORD")
        if not password:
            raise ValueError("Password required. Set password or BC_CONTAINER_PASSWORD env var")

    entries: list[DatasetEntry] = load_dataset_entries(dataset_path, version=version)
    logger.info(f"Found {len(entries)} entries for version {version}")

    run_dir = output_dir / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    for idx, entry in enumerate(entries, 1):
        logger.info(f"{'=' * 80}")
        logger.info(f"Processing entry {idx}/{len(entries)}: {entry.instance_id}")
        logger.info(f"{'=' * 80}")

        result = EvaluationResult(instance_id=entry.instance_id, version=entry.environment_setup_version)

        try:
            clean_repo(repo_path)
            checkout_commit(repo_path, entry.base_commit)
            build_and_publish_projects(repo_path, entry.project_paths, container_name, username, password, entry.environment_setup_version)

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
                )

            # TODO: Extract run detailed from agent (metrics to be discussed)

            apply_patch(repo_path, entry.test_patch, entry.instance_id)
            build_and_publish_projects(repo_path, entry.project_paths, container_name, username, password, entry.environment_setup_version)
            run_tests(entry, container_name, username, password)

            # TODO: Parse test_results to extract pass/fail counts and resolved status
            # For now, assume resolved if no exception
            result.resolved = True

            logger.info(f"Successfully completed {entry.instance_id}")

        except Exception as e:
            result.resolved = False
            result.error_message = str(e)
            logger.error(f"Failed to process {entry.instance_id}: {e}")

        finally:
            result.save(run_dir, f"instance_results_{version.replace('.', '')}.jsonl")

    logger.info(f"{'=' * 80}")
    logger.info("Evaluation complete!")
    logger.info(f"Total entries: {len(entries)}")
    logger.info(f"Results saved to: {run_dir}")
    logger.info(f"{'=' * 80}")


@evaluate_app.command("summarize")
def evaluate_summarize(
    run_id: Annotated[str, typer.Argument(help="Unique identifier for the evaluation run to summarize")],
    output_dir: Annotated[Path, typer.Option(help="Directory containing evaluation results")] = Path("evaluation_results"),
    result_pattern: Annotated[str, typer.Option(help="Pattern for the result files")] = "*.jsonl",
):
    """
    Summarize evaluation results from a completed run.

    Example:
        bcbench evaluate summarize mini_test_run
    """
    run_dir = output_dir / run_id

    if not run_dir.exists():
        logger.error(f"Results directory not found: {run_dir}")
        raise typer.Exit(code=1)

    summarize_results(run_dir, result_pattern)
