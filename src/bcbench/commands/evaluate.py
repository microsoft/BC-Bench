import random
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import cast

import typer
from typing_extensions import Annotated

from bcbench.agent import BCalBackendConfig, run_bcal_agent, run_claude_code, run_copilot_agent
from bcbench.cli_options import (
    ClaudeCodeModel,
    ContainerName,
    ContainerPassword,
    ContainerUsername,
    CopilotModel,
    EvaluationCategoryOption,
    OutputDir,
    RepoPath,
    RunId,
)
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry, NL2ALEntry
from bcbench.evaluate import EvaluationPipeline
from bcbench.logger import get_logger
from bcbench.results import BaseEvaluationResult, CodeReviewResult, ExecutionBasedEvaluationResult, JudgeBasedEvaluationResult
from bcbench.types import AgentMetrics, BCalLLMBackend, ContainerConfig, EvaluationCategory, EvaluationContext, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()

evaluate_app = typer.Typer(help="Evaluate agents on benchmark datasets")


def _prepare_run_dir(output_dir: Path, run_id: str) -> Path:
    run_dir = output_dir / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    return run_dir


@evaluate_app.command("copilot")
def evaluate_copilot(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    container_name: ContainerName = "",
    username: ContainerUsername = "",
    password: ContainerPassword = "",
    model: CopilotModel = "claude-haiku-4.5",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "copilot_test_run",
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
    al_lsp: Annotated[bool, typer.Option("--al-lsp", help="Enable AL LSP server")] = False,
) -> None:
    """
    Evaluate GitHub Copilot CLI on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run copilot' instead.
    """
    entry = category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]
    run_dir = _prepare_run_dir(output_dir, run_id)

    logger.info(f"Running evaluation on entry {entry_id} with GitHub Copilot CLI")

    container = ContainerConfig(name=container_name, username=username, password=password) if container_name else None

    context = EvaluationContext(
        entry=entry,
        repo_path=repo_path,
        result_dir=run_dir,
        container=container,
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
            al_mcp=al_mcp if ctx.container else False,
            al_lsp=al_lsp,
            container_name=ctx.get_container().name if ctx.container else "",
        ),
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")


@evaluate_app.command("claude")
def evaluate_claude_code(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    container_name: ContainerName = "",
    username: ContainerUsername = "",
    password: ContainerPassword = "",
    model: ClaudeCodeModel = "claude-haiku-4-5",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "claude_code_test_run",
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
    al_lsp: Annotated[bool, typer.Option("--al-lsp", help="Enable AL LSP server")] = False,
) -> None:
    """
    Evaluate Claude Code on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run claude' instead.
    """
    entry = category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]
    run_dir = _prepare_run_dir(output_dir, run_id)

    logger.info(f"Running evaluation on entry {entry_id} with Claude Code")

    container = ContainerConfig(name=container_name, username=username, password=password) if container_name else None

    context = EvaluationContext(
        entry=entry,
        repo_path=repo_path,
        result_dir=run_dir,
        container=container,
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
            al_mcp=al_mcp if ctx.container else False,
            al_lsp=al_lsp,
            container_name=ctx.get_container().name if ctx.container else "",
        ),
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {run_dir}")


@evaluate_app.command("bcal")
def evaluate_bcal(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    repo_path: RepoPath = _config.paths.evaluation_results_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "bcal_test_run",
    backend: Annotated[BCalLLMBackend, typer.Option(envvar="BCAL_LLM_BACKEND", help="BCal LLM backend to use")] = BCalLLMBackend.EXTERNAL_COMMAND,
    endpoint: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_ENDPOINT", help="Azure OpenAI endpoint (required for azure-openai backend)")] = None,
    deployment: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_DEPLOYMENT", help="Azure OpenAI deployment (required for azure-openai backend)")] = None,
    llm_command: Annotated[str | None, typer.Option(envvar="BCAL_LLM_COMMAND", help="LLM command (required for external-command backend)")] = None,
    llm_model: Annotated[str | None, typer.Option(envvar="BCAL_LLM_MODEL", help="LLM model/deployment (optional for external-command backend)")] = None,
) -> None:
    """
    Evaluate BCal dotnet tool on single nl2al dataset entry.

    To only run the agent to generate AL code without building, use 'bcbench run bcal' instead.
    """
    category = EvaluationCategory.NL2AL
    entry: NL2ALEntry = cast(NL2ALEntry, category.entry_class.load(category.dataset_path, entry_id=entry_id)[0])
    run_dir = _prepare_run_dir(output_dir, run_id)
    backend_config = BCalBackendConfig(
        backend=backend,
        endpoint=endpoint,
        deployment=deployment,
        command=llm_command,
        model=llm_model,
    )

    logger.info(f"Running evaluation on entry {entry_id} with BCal")

    context = EvaluationContext(
        entry=entry,
        repo_path=repo_path,
        result_dir=run_dir,
        container=None,
        model=backend_config.model_label(),
        agent_name="BCal",
        category=category,
    )

    category.pipeline.execute(
        context,
        lambda ctx: run_bcal_agent(
            entry=cast(NL2ALEntry, ctx.entry),
            repo_path=ctx.repo_path,
            backend_config=backend_config,
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
) -> None:
    """
    Evaluate mock agent on single dataset entry for testing purposes.
    """
    entry = category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]
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

    def setup_workspace(self, entry: BaseDatasetEntry, repo_path: Path) -> None:
        logger.info("Mock pipeline: Skipping workspace setup")

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

        match context.category:
            case EvaluationCategory.BUG_FIX | EvaluationCategory.TEST_GENERATION:
                scenarios = ["success", "build-fail"]
            case EvaluationCategory.CODE_REVIEW:
                scenarios = ["invalid", "valid"]
            case EvaluationCategory.NL2AL:
                scenarios = ["raw", "empty"]
            case _:
                raise ValueError(f"Unsupported category for mock evaluation: {context.category}")

        scenario = random.choice(scenarios)
        logger.info(f"Mock pipeline: Selected scenario: {scenario}")

        result: BaseEvaluationResult
        match scenario:
            case "success":
                result = ExecutionBasedEvaluationResult.create_success(context, "MOCK_PATCH_CONTENT")
            case "build-fail":
                result = ExecutionBasedEvaluationResult.create_build_failure(context, "MOCK_PATCH_CONTENT", "Mock build failure")
            case "invalid":
                result = CodeReviewResult.create_invalid(context, output="MOCK_INVALID_REVIEW_OUTPUT", expected_comments=[])
            case "valid":
                result = CodeReviewResult.create(context, output="[]", expected_comments=[], generated_comments=[], line_tolerance=0)
            case "raw":
                result = JudgeBasedEvaluationResult.create_raw(context, output="MOCK_PATCH_CONTENT")
            case "empty":
                result = JudgeBasedEvaluationResult.create_empty_output(context)
            case _:
                raise ValueError("Invalid mock scenario, this should not happen")

        self.save_result(context, result)
        logger.info(f"Successfully created and saved mock {scenario} result")
