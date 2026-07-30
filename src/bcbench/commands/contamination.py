"""CLI commands for contamination / memorization diagnostics."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from bcbench.cli_options import CopilotModel, EvaluationCategoryOption, OutputDir, RunId
from bcbench.config import get_config
from bcbench.contamination.filepath_identification import FilePathIdentificationResult, IdentificationAggregate, aggregate_results, split_by_cutoff
from bcbench.contamination.runner import load_identification_results, run_filepath_identification
from bcbench.logger import get_logger
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)
_config = get_config()

contamination_app = typer.Typer(help="Contamination / memorization diagnostics for the dataset")

_PATCH_BASED_CATEGORIES = (EvaluationCategory.BUG_FIX, EvaluationCategory.TEST_GENERATION)


@contamination_app.command("file-path-identification")
def filepath_identification(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to evaluate")],
    category: EvaluationCategoryOption = EvaluationCategory.BUG_FIX,
    model: CopilotModel = "claude-haiku-4.5",
    top_k: Annotated[int, typer.Option(min=1, help="Number of candidate file paths to request from the model")] = 3,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "contamination_identification",
) -> None:
    """Context-free file-path identification task (SWE-Bench Illusion methodology).

    Gives the model ONLY the bug report — no repository, no code — and asks which
    file(s) contain the bug, then scores against the files the gold fix patch touches.
    """
    if category not in _PATCH_BASED_CATEGORIES:
        raise typer.BadParameter(f"file-path-identification requires a patch-based category {[c.value for c in _PATCH_BASED_CATEGORIES]}, got '{category.value}'")

    entry = category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]
    result = run_filepath_identification(entry=entry, model=model, category=category.value, top_k=top_k, output_dir=output_dir / run_id)

    if result.error:
        logger.error("Identification errored for %s: %s", entry_id, result.error)
    logger.info("Issue description:\n%s", entry.get_task())
    logger.info("Gold files:      %s", result.gold_files)
    logger.info("Predicted files: %s", result.predicted_files)
    logger.info(
        "exact_hit=%s basename_hit=%s exact_recall=%.2f basename_recall=%.2f",
        result.score.exact_hit,
        result.score.basename_hit,
        result.score.exact_recall,
        result.score.basename_recall,
    )


@contamination_app.command("summarize")
def summarize(
    results_dir: Annotated[Path, typer.Option(help="Directory containing *.file-path-identification.jsonl results")],
    model: Annotated[str, typer.Option(help="Model label for the report")] = "unknown",
    cutoff: Annotated[str | None, typer.Option(help="ISO date (YYYY-MM-DD). Entries created before it are treated as potentially-contaminated; on/after as the clean control.")] = None,
) -> None:
    """Aggregate identification results and report the contamination signal.

    When ``--cutoff`` is given, reports the pre-vs-post delta — the memorization
    signal — rather than a single (convention-inflated) accuracy number.
    """
    if cutoff is not None:
        try:
            date.fromisoformat(cutoff)
        except ValueError as exc:
            raise typer.BadParameter("must be an ISO date (YYYY-MM-DD)", param_hint="--cutoff") from exc

    results = load_identification_results(results_dir)
    if not results:
        logger.error("No *.file-path-identification.jsonl results found under %s", results_dir)
        raise typer.Exit(code=1)

    overall = aggregate_results(results, label="all")
    report = _build_markdown_report(model, overall, results, cutoff)

    print(report)
    _write_step_summary(report)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _aggregate_row(agg: IdentificationAggregate) -> str:
    return f"| {agg.label} | {agg.count} | {_pct(agg.basename_hit_rate)} | {_pct(agg.exact_hit_rate)} | {_pct(agg.mean_basename_recall)} | {_pct(agg.mean_exact_recall)} | {agg.error_count} |"


def _build_markdown_report(model: str, overall: IdentificationAggregate, results: list[FilePathIdentificationResult], cutoff: str | None) -> str:
    header = "| Group | N | Basename hit | Exact hit | Mean basename recall | Mean exact recall | Errors |"
    divider = "| --- | --- | --- | --- | --- | --- | --- |"

    lines = [
        "## File-path identification",
        "",
        f"Model: **{model}** · context-free bug localization (SWE-Bench Illusion methodology).",
        "",
        header,
        divider,
        _aggregate_row(overall),
    ]

    if cutoff:
        pre, post = split_by_cutoff(results, cutoff)
        pre_agg = aggregate_results(pre, label=f"pre-{cutoff} (suspect)")
        post_agg = aggregate_results(post, label=f"{cutoff}+ (control)")
        lines.append(_aggregate_row(pre_agg))
        lines.append(_aggregate_row(post_agg))

        exact_delta = pre_agg.exact_hit_rate - post_agg.exact_hit_rate
        basename_delta = pre_agg.basename_hit_rate - post_agg.basename_hit_rate
        lines += [
            "",
            f"**Contamination signal (exact-path hit, pre - control): {_pct(exact_delta)}**",
            f"(basename-hit delta: {_pct(basename_delta)} — convention-inflated, shown for context)",
            "",
            "> Exact-path hit is the convention-resistant signal: a model can guess an AL basename like `SalesHeader.Table.al` from naming conventions alone, but reproducing the full repository path is far harder without having seen the code. A large positive exact-path delta indicates memorization — the model localizes old/public bugs far better than fresh ones it could not have seen. A small delta means the score is mostly explained by AL naming conventions, not contamination.",
        ]
        if post_agg.scored == 0:
            lines.append("")
            lines.append("> ⚠️ No control (post-cutoff) entries were scored — the delta is not yet meaningful. Add fresh entries.")
    else:
        lines += [
            "",
            "> No `--cutoff` given, so this is an absolute rate only. In AL, file names are highly predictable from conventions, so treat this as a baseline — pass a cutoff date to compare old/public vs fresh entries and get the actual contamination signal.",
        ]

    lines += [
        "",
        "> 📖 How these metrics are calculated: [methodology & citations](https://github.com/microsoft/BC-Bench/blob/main/docs/contamination-file-path-identification.md) · based on [The SWE-Bench Illusion (arXiv:2506.12286)](https://arxiv.org/abs/2506.12286).",
    ]

    return "\n".join(lines)


def _write_step_summary(markdown: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")
