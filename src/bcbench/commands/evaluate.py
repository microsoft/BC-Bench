from pathlib import Path
from typing import Annotated, cast

import typer

from bcbench.application import AgentSelection, EvaluationRequest, evaluate_entry
from bcbench.cli_options import (
    ClaudeCodeModel,
    ContainerCompany,
    ContainerMcpUrl,
    ContainerName,
    ContainerPassword,
    ContainerServerInstance,
    ContainerServerUrl,
    ContainerUsername,
    CopilotModel,
    CopilotModelName,
    EvaluationCategoryOption,
    PRReviewEnginePath,
    RunId,
    resolve_evaluation_runtime,
)
from bcbench.commands.composition import agent_settings, build_category_registry, command_context, judge_invoker, select_agent
from bcbench.logger import get_logger
from bcbench.types import AgentHarness, BCalLLMBackend, EvaluationCategory

logger = get_logger(__name__)

evaluate_app = typer.Typer(help="Evaluate agents on benchmark datasets")


@evaluate_app.command("copilot")
def evaluate_copilot(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    container_name: ContainerName = "",
    username: ContainerUsername = "",
    password: ContainerPassword = "",
    server_url: ContainerServerUrl = "",
    server_instance: ContainerServerInstance = "",
    mcp_url: ContainerMcpUrl = None,
    company: ContainerCompany = "",
    model: CopilotModel = "gpt-5.6-luna",
    repo_path: Annotated[Path | None, typer.Option(help="Path to repository")] = None,
    output_dir: Annotated[Path | None, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)] = None,
    run_id: RunId = "copilot_test_run",
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
    al_lsp: Annotated[bool, typer.Option("--al-lsp", help="Enable AL LSP server")] = False,
    bc_mcp: Annotated[bool, typer.Option("--bc-mcp", help="Enable the Business Central MCP server")] = False,
) -> None:
    """
    Evaluate GitHub Copilot CLI on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run copilot' instead.
    """
    state = command_context(ctx)
    definition = build_category_registry(state)[category]
    runtime = resolve_evaluation_runtime(
        category=definition,
        container_name=container_name,
        username=username,
        container_password=password,
        server_url=server_url,
        server_instance=server_instance,
        mcp_url=mcp_url,
        company=company,
        al_mcp=al_mcp,
        al_lsp=al_lsp,
        bc_mcp=bc_mcp,
    )
    context = evaluate_entry(
        definition,
        EvaluationRequest(
            entry_id=entry_id,
            repo_path=repo_path or state.config.paths.testbed_path,
            output_dir=output_dir or state.config.paths.evaluation_results_path,
            container=runtime.container if runtime else None,
        ),
        select_agent(state, definition, name=AgentHarness.COPILOT, model=model, runtime=runtime, evaluate=True),
        run_id=run_id,
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {context.result_dir}")


@evaluate_app.command("claude")
def evaluate_claude_code(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    container_name: ContainerName = "",
    username: ContainerUsername = "",
    password: ContainerPassword = "",
    server_url: ContainerServerUrl = "",
    server_instance: ContainerServerInstance = "",
    mcp_url: ContainerMcpUrl = None,
    company: ContainerCompany = "",
    model: ClaudeCodeModel = "claude-haiku-4-5",
    repo_path: Annotated[Path | None, typer.Option(help="Path to repository")] = None,
    output_dir: Annotated[Path | None, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)] = None,
    run_id: RunId = "claude_code_test_run",
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
    al_lsp: Annotated[bool, typer.Option("--al-lsp", help="Enable AL LSP server")] = False,
    bc_mcp: Annotated[bool, typer.Option("--bc-mcp", help="Enable the Business Central MCP server")] = False,
) -> None:
    """
    Evaluate Claude Code on single dataset entry.

    To only run the agent to generate a patch without building/testing, use 'bcbench run claude' instead.
    """
    state = command_context(ctx)
    definition = build_category_registry(state)[category]
    runtime = resolve_evaluation_runtime(
        category=definition,
        container_name=container_name,
        username=username,
        container_password=password,
        server_url=server_url,
        server_instance=server_instance,
        mcp_url=mcp_url,
        company=company,
        al_mcp=al_mcp,
        al_lsp=al_lsp,
        bc_mcp=bc_mcp,
    )
    context = evaluate_entry(
        definition,
        EvaluationRequest(
            entry_id=entry_id,
            repo_path=repo_path or state.config.paths.testbed_path,
            output_dir=output_dir or state.config.paths.evaluation_results_path,
            container=runtime.container if runtime else None,
        ),
        select_agent(state, definition, name=AgentHarness.CLAUDE, model=model, runtime=runtime, evaluate=True),
        run_id=run_id,
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {context.result_dir}")


@evaluate_app.command("pr-review")
def evaluate_pr_review(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    model: CopilotModel = "gpt-5.6-luna",
    repo_path: Annotated[Path | None, typer.Option(help="Path to repository")] = None,
    output_dir: Annotated[Path | None, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)] = None,
    run_id: RunId = "pr_review_test_run",
    engine_path: PRReviewEnginePath = None,
) -> None:
    """
    Evaluate BC PR Review on a single code-review entry.

    This production-fidelity runner is fixed to the code-review category, while the same
    category can also run through the generic copilot and claude commands for cross-system
    comparison. The resulting review.json is scored by the shared code-review pipeline.
    Requires a local BC-ALAgents checkout (--engine-path or BC_PR_REVIEW_ROOT),
    PowerShell 7+, and an authenticated Copilot CLI.

    To only generate review.json without scoring, use 'bcbench run pr-review' instead.
    """
    state = command_context(ctx)
    definition = build_category_registry(state)[EvaluationCategory.CODE_REVIEW]
    context = evaluate_entry(
        definition,
        EvaluationRequest(
            entry_id=entry_id,
            repo_path=repo_path or state.config.paths.testbed_path,
            output_dir=output_dir or state.config.paths.evaluation_results_path,
        ),
        select_agent(state, definition, name=AgentHarness.PR_REVIEW, model=model, runtime=None, evaluate=True, engine_path=engine_path),
        run_id=run_id,
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {context.result_dir}")


@evaluate_app.command("bcal")
def evaluate_bcal(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    repo_path: Annotated[Path | None, typer.Option(help="Path to repository")] = None,
    output_dir: Annotated[Path | None, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)] = None,
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
    from bcbench.agent.bcal import BCalBackendConfig, run_bcal_agent
    from bcbench.dataset import NL2ALEntry

    state = command_context(ctx)
    definition = build_category_registry(state)[EvaluationCategory.NL2AL]
    backend_config = BCalBackendConfig(
        backend=backend,
        endpoint=endpoint,
        deployment=deployment,
        command=llm_command,
        model=llm_model,
    )

    logger.info(f"Running evaluation on entry {entry_id} with BCal")

    context = evaluate_entry(
        definition,
        EvaluationRequest(
            entry_id=entry_id,
            repo_path=repo_path or state.config.paths.evaluation_results_path,
            output_dir=output_dir or state.config.paths.evaluation_results_path,
        ),
        AgentSelection(
            name=AgentHarness.BCAL,
            model=backend_config.model_label(),
            runner=lambda context: run_bcal_agent(entry=cast(NL2ALEntry, context.entry), repo_path=context.repo_path, backend_config=backend_config),
        ),
        run_id=run_id,
    )

    logger.info("Evaluation complete!")
    logger.info(f"Results saved to: {context.result_dir}")


@evaluate_app.command("judge-calibration")
def evaluate_judge_calibration(
    ctx: typer.Context,
    model: Annotated[CopilotModelName | None, typer.Option(help="Judge model to use")] = None,
    work_dir: Annotated[Path | None, typer.Option(help="Path to repository")] = None,
    min_accuracy: Annotated[float, typer.Option(help="Fail if judge accuracy falls below this")] = 0.8,
) -> None:
    """Run the LLM judge over the hand-labeled calibration set and report its precision/recall.

    Intended for local/ad-hoc checks of the judge; exits non-zero if accuracy drops below
    the threshold.
    """
    from functools import partial

    from bcbench.categories.code_review.calibration import run_calibration
    from bcbench.categories.code_review.judge import judge_verdicts

    state = command_context(ctx)
    judge_model = model or state.config.judge.code_review_model
    work_dir = work_dir or state.config.paths.testbed_path
    work_dir.mkdir(parents=True, exist_ok=True)
    report = run_calibration(
        work_dir,
        dataset=state.config.paths.dataset_dir / "judge_calibration.jsonl",
        judge=partial(
            judge_verdicts,
            invoke=judge_invoker(agent_settings(state)),
            model=judge_model,
            timeout=state.config.timeout.agent_execution,
            result_filename=state.config.judge.result_file,
        ),
    )

    logger.info(f"Judge calibration ({judge_model}) over {report.total} labeled pairs:")
    logger.info(f"  precision={report.precision:.3f}  recall={report.recall:.3f}  accuracy={report.accuracy:.3f}")
    logger.info(f"  TP={report.true_positives} FP={report.false_positives} TN={report.true_negatives} FN={report.false_negatives}")
    for note in report.misclassified_notes:
        logger.warning(f"  {note}")

    if report.accuracy < min_accuracy:
        logger.error(f"Judge accuracy {report.accuracy:.3f} is below the required {min_accuracy:.3f}")
        raise typer.Exit(code=1)
