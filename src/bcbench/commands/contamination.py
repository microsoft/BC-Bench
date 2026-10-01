"""CLI commands for contamination diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from bcbench.agent.settings import AgentSettings
from bcbench.categories.base import CategoryDefinition
from bcbench.cli_options import CopilotModel, EvaluationCategoryOption, RunId
from bcbench.commands.composition import agent_settings, build_category_registry, command_context
from bcbench.config import Config
from bcbench.contamination.filepath_identification import FilePathIdentificationResult
from bcbench.dataset import BugFixEntry
from bcbench.logger import get_logger
from bcbench.operations import prepare_run_dir
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)


contamination_app = typer.Typer(help="Contamination diagnostics for the dataset")


@contamination_app.command("filepath-identification")
def identification_command(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Entry ID to evaluate")],
    category: EvaluationCategoryOption = EvaluationCategory.BUG_FIX,
    model: CopilotModel = "gpt-5.6-luna",
    output_dir: Annotated[Path | None, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)] = None,
    run_id: RunId = "contamination_identification",
) -> None:
    """Ask a model to identify one buggy file without repository access."""
    state = command_context(ctx)
    definition = build_category_registry(state)[category]
    output_dir = output_dir if output_dir is not None else state.config.paths.evaluation_results_path
    filepath_identification(entry_id, definition, state.config, agent_settings(state), model, output_dir, run_id)


@contamination_app.command("summarize")
def summarize_command(
    ctx: typer.Context,
    results_dir: Annotated[Path, typer.Option(help="Directory containing filepath-identification results")],
) -> None:
    """Aggregate file-path identification results."""
    summarize(results_dir, command_context(ctx).config)


def filepath_identification(
    entry_id: str,
    definition: CategoryDefinition,
    config: Config,
    settings: AgentSettings,
    model: str,
    output_dir: Path,
    run_id: str,
) -> None:
    """Ask a model to identify one buggy file without repository access."""
    from bcbench.contamination.runner import run_filepath_identification

    if definition.name is not EvaluationCategory.BUG_FIX:
        raise typer.BadParameter("filepath-identification currently supports only bug-fix category", param_hint="--category")

    entry: BugFixEntry = BugFixEntry.load(definition.dataset_path, entry_id=entry_id)[0]
    run_dir = prepare_run_dir(output_dir, run_id)
    run_filepath_identification(entry=entry, model=model, result_dir=run_dir, config=config, settings=settings)

    logger.info("FilePath Identification Completed")
    logger.info("Result saved to: %s", run_dir)


def summarize(
    results_dir: Path,
    config: Config,
) -> None:
    """Aggregate file-path identification results."""
    from bcbench.contamination.runner import load_identification_results

    results = load_identification_results(results_dir, config.file_patterns.result_pattern)
    if not results:
        logger.error("No filepath-identification results found under %s", results_dir)
        raise typer.Exit(code=1)

    report = _build_markdown_report(results)
    print(report)
    summary_path = Path(config.env.github_step_summary) if config.env.github_step_summary else None
    _write_step_summary(report, summary_path)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _build_markdown_report(results: list[FilePathIdentificationResult]) -> str:
    first_result = results[0]
    match_rate = sum(result.matches_any_gold_path for result in results) / len(results)
    return "\n".join(
        [
            "## File-path identification",
            "",
            f"- Model: **{first_result.model}**",
            f"- Category: **{first_result.category.value}**",
            "- One-shot bug localization without repository access.",
            "",
            "| Results | Matches any gold path |",
            "| --- | --- |",
            f"| {len(results)} | {_pct(match_rate)} |",
            "",
            "> A match means the single predicted path exactly matched any file path modified by the gold bug-fix patch.",
            "> This absolute match rate is a diagnostic baseline, not standalone evidence of contamination; attribution requires a comparable control set.",
        ]
    )


def _write_step_summary(markdown: str, summary_path: Path | None) -> None:
    if not summary_path:
        return
    with summary_path.open("a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")
