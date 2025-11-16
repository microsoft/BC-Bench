"""CLI commands for evaluating agents on benchmark datasets."""

import random
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
from bcbench.results import EvaluationResult

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
):
    """
    Evaluate mini-bc-agent on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run mini' instead.

    Example:
        uv run bcbench evaluate mini microsoftInternal__NAV-211710 --container-name bcserver
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
    )

    run_evaluation_pipeline(
        context,
        lambda ctx: run_mini_agent(
            entry=ctx.entry,
            repo_path=ctx.repo_path,
            model=ctx.model,
            container_name=ctx.container_name,
            username=ctx.username,
            password=ctx.password,
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
):
    """
    Evaluate GitHub Copilot CLI on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run copilot' instead.

    Example:
        uv run bcbench evaluate copilot microsoftInternal__NAV-211710 --container-name bcserver
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
            output_dir=ctx.result_dir,
        ),
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")


@evaluate_app.command("mock", hidden=True)
def evaluate_mock(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    dataset_path: DatasetPath = _config.paths.dataset_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "mock_run",
):
    """
    Evaluate mock agent on single dataset entry for testing purposes.
    """
    entries: list[DatasetEntry] = load_dataset_entries(dataset_path, entry_id=entry_id)
    entry: DatasetEntry = entries[0]
    logger.info(f"Loaded {entry_id} entry from dataset")

    run_dir: Path = output_dir / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    logger.info(f"Running evaluation on entry {entry_id} with mock agent")

    # Randomize agent metrics to test different scenarios
    metrics_scenarios: list[dict[str, float | int]] = [
        {"agent_execution_time": 0.1, "prompt_tokens": 100, "completion_tokens": 50},
        {"agent_execution_time": 0.2, "prompt_tokens": 250},
        {"agent_execution_time": 0.15},
        {},  # No metrics
        {"prompt_tokens": 500, "completion_tokens": 100},
    ]
    agent_metrics = random.choice(metrics_scenarios)
    mcp_servers = random.choice([["magic-mcp"], None])
    logger.info(f"Using agent metrics: {agent_metrics if agent_metrics else 'None'}")
    logger.info(f"Using MCP servers: {mcp_servers}")

    context = EvaluationContext(
        entry=entry,
        repo_path=Path(),
        result_dir=run_dir,
        container_name="no container",
        username="",
        password="",
        model="mock-model",
        agent_name="mock-agent",
        agent_metrics=agent_metrics if agent_metrics else None,
        mcp_servers=mcp_servers,
    )

    match random.choice(["success", "build-fail", "test-fail"]):
        case "success":
            result = EvaluationResult.create_success(context, "MOCK_PATCH_CONTENT")
        case "build-fail":
            result = EvaluationResult.create_build_failure(context, "MOCK_PATCH_CONTENT", "Mock build failure")
        case "test-fail":
            result = EvaluationResult.create_test_failure(context, "MOCK_PATCH_CONTENT", "Mock test failure")
        case _:
            raise ValueError("Invalid mock scenario, this should not happen")

    result.save(context.result_dir, f"{context.entry.instance_id}{_config.file_patterns.result_pattern}")

    logger.info("Mock evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")
