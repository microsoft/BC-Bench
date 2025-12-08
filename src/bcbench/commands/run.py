"""CLI commands for running agents."""

from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.agent.copilot import run_copilot_agent
from bcbench.agent.copilot.metrics import parse_session_log
from bcbench.agent.mini import run_mini_agent
from bcbench.cli_options import (
    CopilotModel,
    DatasetPath,
    EvaluationCategoryOption,
    FoundryModel,
    OutputDir,
    RepoPath,
)
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry, load_dataset_entries
from bcbench.logger import get_logger
from bcbench.operations import checkout_commit, clean_repo
from bcbench.operations.instruction_operations import copy_problem_statement_folder

logger = get_logger(__name__)
_config = get_config()

run_app = typer.Typer(help="Run agents on single dataset entry")


@run_app.command("mini")
def run_mini(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    model: FoundryModel = "claude-haiku-4-5",
    dataset_path: DatasetPath = _config.paths.dataset_path,
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
):
    """
    Run mini-bc-agent on a single entry to generate a patch (without building/testing).

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run mini microsoftInternal__NAV-211710 --step-limit 5
    """
    entry: DatasetEntry = load_dataset_entries(dataset_path, entry_id=entry_id)[0]

    clean_repo(repo_path)
    checkout_commit(repo_path, entry.base_commit)
    copy_problem_statement_folder(entry, repo_path)

    run_mini_agent(
        entry=entry,
        repo_path=repo_path,
        category=category,
        model="azure/" + model,
        output_dir=output_dir,
    )


@run_app.command("copilot")
def run_copilot(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    model: CopilotModel = "claude-haiku-4.5",
    dataset_path: DatasetPath = _config.paths.dataset_path,
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
):
    """
    Run GitHub Copilot CLI on a single entry to generate a patch (without building/testing).

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run copilot microsoftInternal__NAV-211710
    """
    entry: DatasetEntry = load_dataset_entries(dataset_path, entry_id=entry_id)[0]

    clean_repo(repo_path)
    checkout_commit(repo_path, entry.base_commit)
    copy_problem_statement_folder(entry, repo_path)

    run_copilot_agent(entry=entry, repo_path=repo_path, model=model, category=category, output_dir=output_dir)


@run_app.command("mini-inspector")
def run_mini_inspector(
    path: Annotated[Path, typer.Argument(help="Directory to search for trajectory files or specific trajectory file")],
    pattern: Annotated[str, typer.Option(help="File pattern to match trajectory files")] = f"*{_config.file_patterns.trajectory_pattern}",
):
    """
    Inspect trajectory files in the given directory or a specific trajectory file.

    Example:
        uv run bcbench run mini-inspector ./outputs/mini_agent_runs/
    """
    from minisweagent.run.inspector import TrajectoryInspector

    if path.is_file():
        trajectory_files = [path]
    elif path.is_dir():
        trajectory_files = sorted(path.rglob(pattern))
        if not trajectory_files:
            raise typer.BadParameter(f"No trajectory files found in '{path}'")
    else:
        raise typer.BadParameter(f"Error: Path '{path}' does not exist")

    inspector = TrajectoryInspector(trajectory_files)
    inspector.run()


@run_app.command("copilot-inspector")
def run_copilot_tool_analyzer(path: Annotated[Path, typer.Argument(help="Directory to search for log files or specific log file", exists=True, file_okay=True, dir_okay=False)]):
    """
    Inspect GitHub Copilot CLI session log(s)

    Example:
        uv run bcbench run copilot-inspector ./evaluation_results/
    """

    usage, turn_count = parse_session_log(path)

    print("Tool Usage Summary:")
    print("-" * 40)

    for tool_name, count in sorted(usage.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {tool_name}: {count}")

    print("-" * 40)
    print(f"Total tool calls: {sum(usage.values())}")
    print(f"Total LLM calls: {turn_count}")
