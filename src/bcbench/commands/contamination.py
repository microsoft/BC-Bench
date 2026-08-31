"""CLI commands for contamination diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from bcbench.cli_options import CopilotModel, EvaluationCategoryOption, OutputDir, RunId
from bcbench.config import get_config
from bcbench.contamination.filepath_identification import FilePathIdentificationResult
from bcbench.contamination.runner import load_identification_results, run_filepath_identification
from bcbench.dataset import BugFixEntry
from bcbench.logger import get_logger
from bcbench.operations import prepare_run_dir
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)
_config = get_config()

contamination_app = typer.Typer(help="Contamination diagnostics for the dataset")


@contamination_app.command("filepath-identification")
def filepath_identification(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to evaluate")],
    category: EvaluationCategoryOption = EvaluationCategory.BUG_FIX,
    model: CopilotModel = "gpt-5.6-luna",
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "contamination_identification",
) -> None:
    """Ask a model to identify one buggy file without repository access."""
    if category is not EvaluationCategory.BUG_FIX:
        raise typer.BadParameter("filepath-identification currently supports only bug-fix category", param_hint="--category")

    entry: BugFixEntry = BugFixEntry.load(category.dataset_path, entry_id=entry_id)[0]
    run_dir = prepare_run_dir(output_dir, run_id)
    run_filepath_identification(entry=entry, model=model, result_dir=run_dir)

    logger.info("FilePath Identification Completed")
    logger.info("Result saved to: %s", run_dir)


@contamination_app.command("summarize")
def summarize(
    results_dir: Annotated[Path, typer.Option(help="Directory containing filepath-identification results")],
) -> None:
    """Aggregate file-path identification results."""
    results = load_identification_results(results_dir)
    if not results:
        logger.error("No filepath-identification results found under %s", results_dir)
        raise typer.Exit(code=1)

    report = _build_markdown_report(results)
    print(report)
    _write_step_summary(report)


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


def _write_step_summary(markdown: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")
