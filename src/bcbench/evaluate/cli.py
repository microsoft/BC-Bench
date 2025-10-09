"""CLI commands for evaluating agents on benchmark datasets."""

import os
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

from bcbench.core.utils import DATASET_PATH, NAV_REPO_PATH
from bcbench.core.logger import get_logger
from bcbench.core.git_operations import clean_repo, checkout_commit, apply_patch
from bcbench.core.bc_operations import build_and_publish_projects, run_tests
from bcbench.dataset.dataset_loader import load_dataset_entries
from bcbench.agent.mini import run_mini_agent

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

    entries = load_dataset_entries(dataset_path, version=version)
    logger.info(f"Found {len(entries)} entries for version {version}")

    for idx, entry in enumerate(entries, 1):
        logger.info(f"\n{'=' * 80}")
        logger.info(f"Processing entry {idx}/{len(entries)}: {entry.instance_id}")
        logger.info(f"{'=' * 80}\n")

        try:
            _evaluate_single_entry(
                entry=entry,
                repo_path=repo_path,
                container_name=container_name,
                username=username,
                password=password,
                step_limit=step_limit,
                cost_limit=cost_limit,
            )
            logger.info(f"Successfully completed {entry.instance_id}")
        except Exception as e:
            logger.error(f"Failed to process {entry.instance_id}: {e}")
            continue

        logger.info(f"\nEvaluation complete. Processed {len(entries)} entries.")


def _evaluate_single_entry(
    entry,
    repo_path: Path,
    container_name: str,
    username: str,
    password: str,
    step_limit: int,
    cost_limit: float,
) -> None:
    """Evaluate a single entry through the full pipeline."""

    clean_repo(repo_path)
    checkout_commit(repo_path, entry.base_commit)
    build_and_publish_projects(repo_path, entry.project_paths, container_name, username, password)

    run_mini_agent(
        dataset_path=DATASET_PATH,
        entry_id=entry.instance_id,
        repo_path=repo_path,
        use_container=False,
        container_name=container_name,
        username=username,
        password=password,
        step_limit=step_limit,
        cost_limit=cost_limit,
    )

    apply_patch(repo_path, entry.test_patch, entry.instance_id)
    build_and_publish_projects(repo_path, entry.project_paths, container_name, username, password)
    run_tests(entry, container_name, username, password)
