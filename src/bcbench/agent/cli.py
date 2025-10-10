"""CLI commands for running agents."""

from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

from bcbench.core.utils import DATASET_PATH, NAV_REPO_PATH
from bcbench.core.git_operations import clean_repo
from bcbench.agent.mini import run_mini_agent
from bcbench.core.logger import get_logger

logger = get_logger(__name__)

run_app = typer.Typer(help="Run agents on single dataset entry")


@run_app.command("mini")
def run_mini(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    repo_path: Annotated[Path, typer.Option(help="Path to NAV repository")] = NAV_REPO_PATH,
    enable_bc_tools: Annotated[bool, typer.Option(help="Whether to enable BC tools for the agent (build and test)")] = False,
    container_name: Annotated[Optional[str], typer.Option(help="BC container name (required if --use-container)")] = None,
    username: Annotated[str, typer.Option(help="Username for BC container")] = "admin",
    password: Annotated[Optional[str], typer.Option(help="Password for BC container (or set BC_CONTAINER_PASSWORD env var)")] = None,
    step_limit: Annotated[int, typer.Option(help="Maximum number of agent steps")] = 20,
    cost_limit: Annotated[float, typer.Option(help="Maximum cost limit for agent")] = 1.0,
):
    """
    Run mini-bc-agent on a single dataset entry (for local testing).

    Example:
        bcbench run mini microsoftInternal__NAV-210528 --step-limit 5
    """

    clean_repo(repo_path)

    run_mini_agent(
        dataset_path=dataset_path,
        entry_id=entry_id,
        repo_path=repo_path,
        enable_bc_tools=enable_bc_tools,
        container_name=container_name,
        username=username,
        password=password,
        step_limit=step_limit,
        cost_limit=cost_limit,
    )
