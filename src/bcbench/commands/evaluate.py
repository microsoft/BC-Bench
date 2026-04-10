import random
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.agent import run_claude_code, run_copilot_agent, run_mini_agent
from bcbench.cli_options import (
    ClaudeCodeModel,
    ContainerName,
    ContainerPassword,
    ContainerUsername,
    CopilotModel,
    EvaluationCategoryOption,
    FoundryModel,
    OutputDir,
    RepoPath,
    RunId,
)
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry, BugFixEntry
from bcbench.dataset.counterfactual_loader import load_counterfactual_entries
from bcbench.evaluate import EvaluationPipeline
from bcbench.logger import get_logger
from bcbench.results import BaseEvaluationResult
from bcbench.types import AgentMetrics, ContainerConfig, EvaluationContext, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()

_CF_PATTERN = re.compile(r"__cf-\d+$")


def _load_entry(entry_id: str, category) -> BugFixEntry:
    """Load a dataset entry, auto-detecting counterfactual entries by ID pattern."""
    if _CF_PATTERN.search(entry_id):
        cf_path = _config.paths.counterfactual_dataset_path
        base_path = _config.paths.dataset_dir / "bcbench.jsonl"
        pairs = load_counterfactual_entries(cf_path, base_path, entry_id=entry_id)
        cf_entry, base_entry = pairs[0]
        merged = cf_entry.to_dataset_entry(base_entry)
        logger.info(f"Loaded counterfactual entry {cf_entry.instance_id} (base: {cf_entry.base_instance_id})")
        return merged
    return category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]


evaluate_app = typer.Typer(help="Evaluate agents on benchmark datasets")


def _prepare_run_dir(output_dir: Path, run_id: str) -> Path:
    run_dir = output_dir / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    return run_dir


@evaluate_app.command("mini")
def evaluate_mini(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    container_name: ContainerName,
    username: ContainerUsername,
    password: ContainerPassword,
    category: EvaluationCategoryOption,
    model: FoundryModel = "gpt-5.1-codex-mini",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "mini_test_run",
):
    """
    Evaluate mini-bc-agent on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run mini' instead.
    """
    entry = _load_entry(entry_id, category)
    run_dir = _prepare_run_dir(output_dir, run_id)

    logger.info(f"Running evaluation on entry {entry_id} with mini-bc-agent")

    context = EvaluationContext(
        entry=entry,
        repo_path=repo_path,
        result_dir=run_dir,
        container=ContainerConfig(name=container_name, username=username, password=password),
        model=model,
        agent_name="mini-bc-agent",
        category=category,
    )

    pipeline = category.pipeline
    pipeline.execute(
        context,
        lambda ctx: run_mini_agent(
            entry=ctx.entry,
            repo_path=ctx.repo_path,
            category=category,
            model="azure/" + model,
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
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "copilot_test_run",
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
):
    """
    Evaluate GitHub Copilot CLI on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run copilot' instead.
    """
    entry = _load_entry(entry_id, category)
    run_dir = _prepare_run_dir(output_dir, run_id)

    logger.info(f"Running evaluation on entry {entry_id} with GitHub Copilot CLI")

    context = EvaluationContext(
        entry=entry,
        repo_path=repo_path,
        result_dir=run_dir,
        container=ContainerConfig(name=container_name, username=username, password=password),
        model=model,
        agent_name="GitHub Copilot",
        category=category,
    )

    pipeline = category.pipeline
    pipeline.execute(
        context,
        lambda ctx: run_copilot_agent(
            entry=ctx.entry,
            repo_path=ctx.repo_path,
            category=category,
            model=ctx.model,
            output_dir=ctx.result_dir,
            al_mcp=al_mcp,
            container_name=ctx.get_container().name,
        ),
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")


@evaluate_app.command("claude")
def evaluate_claude_code(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    container_name: ContainerName,
    username: ContainerUsername,
    password: ContainerPassword,
    category: EvaluationCategoryOption,
    model: ClaudeCodeModel = "claude-haiku-4-5",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "claude_code_test_run",
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
):
    """
    Evaluate Claude Code on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run claude' instead.
    """
    entry = _load_entry(entry_id, category)
    run_dir = _prepare_run_dir(output_dir, run_id)

    logger.info(f"Running evaluation on entry {entry_id} with Claude Code")

    context = EvaluationContext(
        entry=entry,
        repo_path=repo_path,
        result_dir=run_dir,
        container=ContainerConfig(name=container_name, username=username, password=password),
        model=model,
        agent_name="Claude Code",
        category=category,
    )

    pipeline = category.pipeline
    pipeline.execute(
        context,
        lambda ctx: run_claude_code(
            entry=ctx.entry,
            repo_path=ctx.repo_path,
            category=category,
            model=ctx.model,
            output_dir=ctx.result_dir,
            al_mcp=al_mcp,
            container_name=ctx.get_container().name,
        ),
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")


@evaluate_app.command("mock", hidden=True)
def evaluate_mock(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "mock_run",
):
    """
    Evaluate mock agent on single dataset entry for testing purposes.
    """
    entry = _load_entry(entry_id, category)
    run_dir = _prepare_run_dir(output_dir, run_id)

    logger.info(f"Running evaluation on entry {entry_id} with mock agent")

    context = EvaluationContext(
        entry=entry,
        repo_path=Path(),
        result_dir=run_dir,
        model="mock-model",
        agent_name="mock-agent",
        category=category,
    )

    pipeline = MockEvaluationPipeline()
    pipeline.execute(context, lambda ctx: (None, None))

    logger.info("Mock evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")


class MockEvaluationPipeline(EvaluationPipeline[BaseDatasetEntry]):
    """Mock pipeline for testing evaluation infrastructure.

    This pipeline simulates agent execution without requiring actual BC container setup.
    It randomly generates different scenarios to test result handling and serialization.
    """

    def setup(self, context: EvaluationContext[BaseDatasetEntry]) -> None:
        logger.info("Mock pipeline: Skipping setup")

    def run_agent(self, context: EvaluationContext[BaseDatasetEntry], agent_runner: Callable) -> None:
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

    def evaluate(self, context: EvaluationContext[BaseDatasetEntry]) -> None:
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
