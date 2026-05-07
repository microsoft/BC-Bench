import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

import typer
from typing_extensions import Annotated

from bcbench.cli_options import EvaluationCategoryOption, OutputDir, RunId
from bcbench.config import get_config
from bcbench.logger import get_logger
from bcbench.results import (
    BaseEvaluationResult,
    EvaluationResultSummary,
    ExecutionBasedEvaluationResultSummary,
    Leaderboard,
    LeaderboardAggregate,
    create_console_summary,
    create_github_job_summary,
    write_bceval_results,
)

logger = get_logger(__name__)


_config = get_config()

result_app = typer.Typer(help="Process and display evaluation results")


@result_app.command("summarize")
def result_summarize(
    run_id: RunId,
    category: EvaluationCategoryOption,
    result_dir: OutputDir = _config.paths.evaluation_results_path,
    result_pattern: Annotated[str, typer.Option(help="Pattern for the per instances result files")] = f"*{_config.file_patterns.result_pattern}",
    summary_output: Annotated[str, typer.Option(help="Output filename for summary JSON")] = "evaluation_summary.json",
    bceval_output: Annotated[str, typer.Option(help="Output filename for bceval results")] = "bceval_results.jsonl",
    poc_checklist: Annotated[
        bool,
        typer.Option(
            "--poc-checklist",
            help="POC: attach hardcoded LMChecklist assertions to the bceval 'expected' field so bc-eval's lm_checklist evaluator can score this run. Intended to demonstrate LLM-as-judge integration against the existing bug-fix pipeline.",
        ),
    ] = False,
) -> None:
    """
    Summarize evaluation results from a completed run.

    Aggregates individual instance results, displays job summaries and generates bceval output format.
    """
    run_dir: Path = result_dir / run_id

    if not run_dir.exists():
        logger.error(f"Results directory not found: {run_dir}")
        raise typer.Exit(code=1)

    result_files = list(run_dir.rglob(result_pattern))
    if not result_files:
        logger.error(f"No result files matching '{result_pattern}' found in {run_dir}")
        raise typer.Exit(code=1)

    # Filter to only instance-specific result files (exclude combined results and summaries)
    instance_pattern_regex = re.compile(_config.file_patterns.instance_pattern)
    result_files = [f for f in result_files if instance_pattern_regex.match(f.stem)]

    if not result_files:
        logger.error(f"No instance-specific result files found in {run_dir}")
        raise typer.Exit(code=1)

    results: list[BaseEvaluationResult] = []
    for results_path in result_files:
        logger.info(f"Reading results from: {results_path}")
        with open(results_path) as f:
            results.extend(BaseEvaluationResult.from_json(json.loads(line)) for line in f if line.strip())

    if not results:
        logger.error("No results found in the result files")
        raise typer.Exit(code=1)

    write_bceval_results(results, run_dir, run_id, bceval_output, category, include_poc_checklist=poc_checklist)

    summary = EvaluationResultSummary.from_results(results, run_id=run_id)

    if _config.env.github_actions:
        create_github_job_summary(results, summary)
    else:
        create_console_summary(results, summary)

    summary.save(run_dir, summary_output)


def _get_combination_key(result: EvaluationResultSummary) -> tuple[str, str, str | None, str]:
    exp_key = None
    if result.experiment and not result.experiment.is_empty():
        exp_key = json.dumps(result.experiment.model_dump(mode="json"), sort_keys=True)
    return (result.agent_name, result.model, exp_key, result.benchmark_version)


def _rebuild_aggregates(runs: list[ExecutionBasedEvaluationResultSummary]) -> list[LeaderboardAggregate]:
    grouped: defaultdict[tuple[str, str, str | None, str], list[ExecutionBasedEvaluationResultSummary]] = defaultdict(list)
    for run in runs:
        grouped[_get_combination_key(run)].append(run)
    return [LeaderboardAggregate.from_runs(group) for group in grouped.values()]


@result_app.command("update")
def result_update(
    evaluation_summary: Annotated[Path, typer.Argument(help="Path to a single evaluation run's summary JSON", exists=True, file_okay=True, dir_okay=False)],
    leaderboard_dir: Annotated[Path, typer.Option(help="Path to the directory containing category-specific leaderboard files")] = _config.paths.leaderboard_dir,
    n: Annotated[int, typer.Option(help="Max number of runs to store per agent+model+experiment combination")] = 5,
) -> None:
    """
    Update the public leaderboard with a new evaluation summary.

    Takes a single evaluation run's summary and updates the appropriate category-specific leaderboard file.
    Stores up to n runs per combination, removing the oldest when exceeding n.
    """
    logger.info(f"Loading evaluation summary from: {evaluation_summary}")
    with open(evaluation_summary, encoding="utf-8") as f:
        new_result = ExecutionBasedEvaluationResultSummary.model_validate_json(f.read())

    logger.info(f"Processing result for agent '{new_result.agent_name}' with model '{new_result.model}' in category '{new_result.category.value}'")

    leaderboard_path = leaderboard_dir / f"{new_result.category.value}.json"
    logger.info(f"Using leaderboard file: {leaderboard_path}")

    # Load existing leaderboard
    leaderboard: Leaderboard = Leaderboard.load(leaderboard_path)
    runs: list[ExecutionBasedEvaluationResultSummary] = list(leaderboard.runs)
    logger.info(f"Loaded {len(runs)} existing runs")

    # Find runs matching this combination
    new_result_key = _get_combination_key(new_result)
    matching_runs: list[ExecutionBasedEvaluationResultSummary] = [r for r in runs if _get_combination_key(r) == new_result_key]
    other_runs: list[ExecutionBasedEvaluationResultSummary] = [r for r in runs if _get_combination_key(r) != new_result_key]

    if len(matching_runs) < n:
        logger.info(f"Adding run ({len(matching_runs) + 1}/{n}) for '{new_result.agent_name}' + '{new_result.model}'")
        matching_runs.append(new_result)
    else:
        matching_runs.sort(key=lambda x: x.date)
        logger.info(f"Replacing oldest run (date: {matching_runs[0].date}) for '{new_result.agent_name}' + '{new_result.model}'")
        matching_runs = [*matching_runs[1:], new_result]

    # Combine and rebuild aggregates
    all_runs: list[ExecutionBasedEvaluationResultSummary] = other_runs + matching_runs
    aggregates = _rebuild_aggregates(all_runs)

    # Write back
    leaderboard = Leaderboard(runs=all_runs, aggregate=aggregates)
    with open(leaderboard_path, "w", encoding="utf-8") as f:
        json.dump(leaderboard.to_dict(), f, indent=2)
        f.write("\n")

    logger.info(f"Successfully updated leaderboard at: {leaderboard_path}")


@result_app.command("refresh")
def result_refresh(
    leaderboard_dir: Annotated[Path, typer.Option(help="Path to the directory containing category-specific leaderboard files")] = _config.paths.leaderboard_dir,
) -> None:
    """
    Refresh all leaderboard aggregates without adding new data.

    Recalculates aggregate metrics for all category-specific leaderboard files
    based on their existing runs. Useful when the aggregation logic has changed.
    """
    leaderboard_files: list[Path] = list(leaderboard_dir.glob("*.json"))

    if not leaderboard_files:
        logger.error(f"No leaderboard files found in: {leaderboard_dir}")
        raise typer.Exit(code=1)

    logger.info(f"Found {len(leaderboard_files)} leaderboard file(s) to refresh")

    for leaderboard_path in leaderboard_files:
        logger.info(f"Refreshing: {leaderboard_path.name}")

        leaderboard: Leaderboard = Leaderboard.load(leaderboard_path)
        runs: list[ExecutionBasedEvaluationResultSummary] = list(leaderboard.runs)

        if not runs:
            logger.warning(f"No runs found in {leaderboard_path.name}, skipping")
            continue

        # Rebuild aggregates from existing runs
        aggregates = _rebuild_aggregates(runs)

        # Write back
        leaderboard = Leaderboard(runs=runs, aggregate=aggregates)
        with open(leaderboard_path, "w", encoding="utf-8") as f:
            json.dump(leaderboard.to_dict(), f, indent=2)
            f.write("\n")

        logger.info(f"Refreshed {leaderboard_path.name}: {len(runs)} runs -> {len(aggregates)} aggregates")


def _to_bceval_row(result: BaseEvaluationResult, assertions: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "id": result.instance_id,
        # lm_checklist's prompt only requires `output` + `expected.assertions`; `input` is purely contextual.
        "input": "",
        "expected": {"assertions": assertions},
        "output": result.output,
        "metadata": {
            "model": result.model,
            "agent_name": result.agent_name,
            "category": result.category.value,
        },
        "tags": [],
    }


# POC checklist for ad-hoc local LMChecklist scoring. Edit this list to try different assertions.
_LMCHECK_ASSERTIONS: list[dict[str, str]] = [
    {"text": "The generated patch does not disable, delete, or skip any existing tests.", "level": "critical"},
    {"text": "The generated patch does not contain TODO/FIXME comments or commented-out code.", "level": "expected"},
]


_DEFAULT_LMCHECK_OUTPUT = _config.paths.evaluation_results_path / "lmcheck" / "bceval.jsonl"


@result_app.command("to-bceval")
def result_to_bceval(
    result_file: Annotated[Path, typer.Argument(help="Per-instance evaluation result JSONL (BaseEvaluationResult schema, one row per line).", exists=True, file_okay=True, dir_okay=False)],
    output_file: Annotated[Path, typer.Option("--output", "-o", help="Where to write the bceval JSONL. The parent directory is wiped and recreated.")] = _DEFAULT_LMCHECK_OUTPUT,
) -> None:
    """
    Convert per-instance BaseEvaluationResult(s) into a bceval-compatible JSONL with a hardcoded LMChecklist (see `_LMCHECK_ASSERTIONS` in this file).
    Then run bceval directly to score it (PowerShell):

    \b
        uv run bcbench result to-bceval evaluation_results\\<run-id>\\<inst>.jsonl
        bceval metrics calculate --input-file evaluation_results\\lmcheck\\bceval.jsonl --evaluators lm_checklist --eval-run-name "local" --output-file evaluation_results\\lmcheck\\results.json

    Requires `bceval` on PATH (`uv tool install --python 3.12 --editable <bc-eval source> --force`) and `az login`.
    """
    result = BaseEvaluationResult.from_json(json.loads(result_file.read_text(encoding="utf-8")))

    out_dir = output_file.parent
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as sink:
        sink.write(json.dumps(_to_bceval_row(result, _LMCHECK_ASSERTIONS)) + "\n")
    logger.info(f"Wrote 1 bceval row to: {output_file}")
