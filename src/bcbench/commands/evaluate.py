import random
import shutil
from collections.abc import Callable
from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.agent import run_copilot_agent, run_mini_agent
from bcbench.cli_options import (
    ContainerName,
    ContainerPassword,
    ContainerUsername,
    CopilotModel,
    DatasetPath,
    EvaluationCategoryOption,
    FoundryModel,
    OutputDir,
    RepoPath,
    RunId,
)
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry, load_dataset_entries
from bcbench.evaluate import EvaluationPipeline, create_pipeline
from bcbench.logger import get_logger
from bcbench.results import BaseEvaluationResult
from bcbench.types import AgentMetrics, EvaluationContext, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()

evaluate_app = typer.Typer(help="Evaluate agents on benchmark datasets")


@evaluate_app.command("mini")
def evaluate_mini(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    container_name: ContainerName,
    username: ContainerUsername,
    password: ContainerPassword,
    category: EvaluationCategoryOption,
    model: FoundryModel = "claude-haiku-4-5",
    dataset_path: DatasetPath = _config.paths.dataset_path,
    repo_path: RepoPath = _config.paths.testbed_path,
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
        model="azure/" + model,
        agent_name="mini-bc-agent",
        category=category,
    )

    pipeline = create_pipeline(category)
    pipeline.execute(
        context,
        lambda ctx: run_mini_agent(
            entry=ctx.entry,
            repo_path=ctx.repo_path,
            category=category,
            model=ctx.model,
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
    category: EvaluationCategoryOption,
    model: CopilotModel = "claude-haiku-4.5",
    dataset_path: DatasetPath = _config.paths.dataset_path,
    repo_path: RepoPath = _config.paths.testbed_path,
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
        category=category,
    )

    pipeline = create_pipeline(category)
    pipeline.execute(
        context,
        lambda ctx: run_copilot_agent(
            entry=ctx.entry,
            repo_path=ctx.repo_path,
            category=category,
            model=ctx.model,
            output_dir=ctx.result_dir,
        ),
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")


@evaluate_app.command("mock", hidden=True)
def evaluate_mock(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
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

    context = EvaluationContext(
        entry=entry,
        repo_path=Path(),
        result_dir=run_dir,
        container_name="no container",
        username="",
        password="",
        model="mock-model",
        agent_name="mock-agent",
        category=category,
    )

    pipeline = MockEvaluationPipeline()
    pipeline.execute(context, lambda ctx: (None, None))

    logger.info("Mock evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")


class MockEvaluationPipeline(EvaluationPipeline):
    """Mock pipeline for testing evaluation infrastructure.

    This pipeline simulates agent execution without requiring actual BC container setup.
    It randomly generates different scenarios to test result handling and serialization.
    """

    def setup(self, context: EvaluationContext) -> None:
        logger.info("Mock pipeline: Skipping setup")

    def run_agent(self, context: EvaluationContext, agent_runner: Callable) -> None:
        """Generate random agent metrics and experiment configuration."""
        logger.info("Mock pipeline: Generating random metrics and experiment configuration")

        # Randomize agent metrics to test different scenarios
        metrics_scenarios: list[AgentMetrics | None] = [
            AgentMetrics(execution_time=0.1, llm_duration=0.05, prompt_tokens=100, completion_tokens=50, tool_usage={"bash": 5, "view": 3, "edit": 2}, turn_count=7),
            AgentMetrics(execution_time=0.2, llm_duration=0.1, prompt_tokens=250, tool_usage={"bash": 10, "search": 4}),
            AgentMetrics(execution_time=0.15, llm_duration=0.07, tool_usage={"view": 8}, turn_count=4),
            AgentMetrics(),
            None,
            AgentMetrics(prompt_tokens=500, completion_tokens=100, tool_usage={"bash": 3, "view": 2, "edit": 1, "search": 5}),
        ]
        context.metrics = random.choice(metrics_scenarios)

        # Randomize experiment configuration to test different scenarios
        experiment_config_scenarios: list[ExperimentConfiguration | None] = [
            ExperimentConfiguration(mcp_servers=["magic-mcp"], custom_instructions=True, custom_agent="custom-agent-v1"),
            ExperimentConfiguration(mcp_servers=["magic-mcp"]),
            ExperimentConfiguration(custom_instructions=True),
            None,
            ExperimentConfiguration(),
            ExperimentConfiguration(custom_agent="custom-agent-v1"),
        ]
        context.experiment = random.choice(experiment_config_scenarios)

        logger.info(f"Using agent metrics: {context.metrics}")
        logger.info(f"Using experiment configuration: {context.experiment}")

    def evaluate(self, context: EvaluationContext) -> None:
        """Create random evaluation result to test different outcome scenarios."""
        logger.info("Mock pipeline: Generating random evaluation result")

        # Randomly choose success, build failure, or test failure
        scenario = random.choice(["success", "build-fail", "test-fail"])
        logger.info(f"Mock pipeline: Selected scenario: {scenario}")

        result: BaseEvaluationResult
        match scenario:
            case "success":
                result = BaseEvaluationResult.create_success(context, "MOCK_PATCH_CONTENT")
            case "build-fail":
                result = BaseEvaluationResult.create_build_failure(context, "MOCK_PATCH_CONTENT", "Mock build failure")
            case "test-fail":
                result = BaseEvaluationResult.create_test_failure(context, "MOCK_PATCH_CONTENT", "Mock test failure")
            case _:
                raise ValueError("Invalid mock scenario, this should not happen")

        self.save_result(context, result)
        logger.info(f"Successfully created and saved mock {scenario} result")
