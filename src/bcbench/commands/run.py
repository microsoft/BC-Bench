"""CLI commands for running agents."""

from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.agent.copilot import run_copilot_agent
from bcbench.agent.mini import run_mini_agent
from bcbench.dataset import DatasetEntry, load_dataset_entries
from bcbench.logger import get_logger
from bcbench.operations import checkout_commit, clean_repo
from bcbench.utils import DATASET_PATH, NAV_REPO_PATH

logger = get_logger(__name__)

run_app = typer.Typer(help="Run agents on single dataset entry")


@run_app.command("mini")
def run_mini(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    repo_path: Annotated[Path, typer.Option(help="Path to NAV repository")] = NAV_REPO_PATH,
    enable_bc_tools: Annotated[
        bool,
        typer.Option(help="Whether to enable BC tools for the agent (build and test)"),
    ] = False,
    container_name: Annotated[str | None, typer.Option(help="BC container name (required if --use-container)")] = None,
    username: Annotated[str, typer.Option(help="Username for BC container")] = "admin",
    password: Annotated[
        str | None,
        typer.Option(help="Password for BC container (or set BC_CONTAINER_PASSWORD env var)"),
    ] = None,
    step_limit: Annotated[int, typer.Option(help="Maximum number of agent steps")] = 20,
    cost_limit: Annotated[float, typer.Option(help="Maximum cost limit for agent")] = 1.0,
    output_dir: Annotated[Path | None, typer.Option(help="Directory to save output result")] = None,
):
    """
    Run mini-bc-agent on a single entry to generate a patch (without building/testing).

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

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
        output_dir=output_dir,
    )


@run_app.command("copilot")
def run_copilot(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    repo_path: Annotated[Path, typer.Option(help="Path to NAV repository")] = NAV_REPO_PATH,
    output_dir: Annotated[Path | None, typer.Option(help="Directory to save output result")] = None,
):
    """
    Run GitHub Copilot CLI on a single entry to generate a patch (without building/testing).

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        bcbench run copilot microsoftInternal__NAV-210528
    """
    entry: DatasetEntry = load_dataset_entries(dataset_path, entry_id=entry_id)[0]

    clean_repo(repo_path)
    checkout_commit(repo_path, entry.base_commit)

    run_copilot_agent(entry=entry, repo_path=repo_path)


@run_app.command("mini-inspector")
def run_mini_inspector(
    path: Annotated[Path, typer.Argument(help="Directory to search for trajectory files or specific trajectory file")],
):
    """
    Inspect trajectory files (*.traj.json) in the given directory or a specific trajectory file.

    Example:
        bcbench run mini-inspector ./outputs/mini_agent_runs/
    """
    from minisweagent.run.inspector import TrajectoryInspector

    if path.is_file():
        trajectory_files = [path]
    elif path.is_dir():
        trajectory_files = sorted(path.rglob("*.traj.json"))
        if not trajectory_files:
            raise typer.BadParameter(f"No trajectory files found in '{path}'")
    else:
        raise typer.BadParameter(f"Error: Path '{path}' does not exist")

    inspector = TrajectoryInspector(trajectory_files)
    inspector.run()
