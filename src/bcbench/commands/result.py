import json
import re
from collections import defaultdict
from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.cli_options import DatasetPath, OutputDir, RunId
from bcbench.config import get_config
from bcbench.logger import get_logger
from bcbench.results import (
    BaseEvaluationResult,
    EvaluationResultSummary,
    Leaderboard,
    LeaderboardAggregate,
    create_console_summary,
    create_github_job_summary,
    create_result_from_json,
    write_bceval_results,
)
from bcbench.results.reviewer import run_instance_reviewer, run_reviewer

logger = get_logger(__name__)


_config = get_config()

result_app = typer.Typer(help="Process and display evaluation results")


@result_app.command("review")
def result_review(
    results_file: Annotated[Path, typer.Argument(help="Path to results JSONL file to review (or directory if --instance-id is used)", exists=True, file_okay=True, dir_okay=True)],
    dataset_path: DatasetPath = _config.paths.dataset_path,
    instance_id: Annotated[str | None, typer.Option("--instance-id", "-i", help="Review a single instance across all runs in a directory")] = None,
):
    """
    Review evaluation results and annotate failure categories using a TUI.

    Opens a split-pane view showing expected (gold patch) vs actual (agent output).
    Use j/k or arrows to navigate, 1-7 to select failure category.
    Categories are auto-saved on navigate and quit.

    Two modes:
    - Default: Review all unresolved results in a single JSONL file
    - With --instance-id: Review one instance across all runs in a directory
    """
    if instance_id:
        if not results_file.is_dir():
            logger.error(f"When using --instance-id, the path must be a directory containing JSONL files: {results_file}")
            raise typer.Exit(code=1)
        run_instance_reviewer(results_file, instance_id, dataset_path)
    else:
        if not results_file.is_file():
            logger.error(f"Expected a JSONL file, got directory: {results_file}. Use --instance-id to review across runs.")
            raise typer.Exit(code=1)
        run_reviewer(results_file, dataset_path)


@result_app.command("summarize")
def result_summarize(
    run_id: RunId,
    result_dir: OutputDir = _config.paths.evaluation_results_path,
    result_pattern: Annotated[str, typer.Option(help="Pattern for the per instances result files")] = f"*{_config.file_patterns.result_pattern}",
    dataset_path: DatasetPath = _config.paths.dataset_path,
    summary_output: Annotated[str, typer.Option(help="Output filename for summary JSON")] = "evaluation_summary.json",
    bceval_output: Annotated[str, typer.Option(help="Output filename for bceval results")] = "bceval_results.jsonl",
):
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
            results.extend(create_result_from_json(json.loads(line)) for line in f if line.strip())

    if not results:
        logger.error("No results found in the result files")
        raise typer.Exit(code=1)

    write_bceval_results(results, run_dir, run_id, dataset_path, bceval_output)

    if _config.env.github_actions:
        create_github_job_summary(results)
    else:
        create_console_summary(results)

    # Save summary JSON
    summary = EvaluationResultSummary.from_results(results, run_id=run_id)
    summary.save(run_dir, summary_output)


def _get_combination_key(result: EvaluationResultSummary) -> tuple[str, str, str | None]:
    exp_key = None
    if result.experiment and not result.experiment.is_empty():
        exp_key = json.dumps(result.experiment.model_dump(mode="json"), sort_keys=True)
    return (result.agent_name, result.model, exp_key)


def _rebuild_aggregates(runs: list[EvaluationResultSummary]) -> list[LeaderboardAggregate]:
    grouped: defaultdict[tuple[str, str, str | None], list[EvaluationResultSummary]] = defaultdict(list)
    for run in runs:
        grouped[_get_combination_key(run)].append(run)
    return [LeaderboardAggregate.from_runs(group) for group in grouped.values()]


@result_app.command("update")
def result_update(
    evaluation_summary: Annotated[Path, typer.Argument(help="Path to a single evaluation run's summary JSON", exists=True, file_okay=True, dir_okay=False)],
    leaderboard_dir: Annotated[Path, typer.Option(help="Path to the directory containing category-specific leaderboard files")] = _config.paths.leaderboard_dir,
    n: Annotated[int, typer.Option(help="Max number of runs to store per agent+model+experiment combination")] = 5,
):
    """
    Update the public leaderboard with a new evaluation summary.

    Takes a single evaluation run's summary and updates the appropriate category-specific leaderboard file.
    Stores up to n runs per combination, removing the oldest when exceeding n.
    """
    logger.info(f"Loading evaluation summary from: {evaluation_summary}")
    with open(evaluation_summary, encoding="utf-8") as f:
        new_result = EvaluationResultSummary.model_validate_json(f.read())

    logger.info(f"Processing result for agent '{new_result.agent_name}' with model '{new_result.model}' in category '{new_result.category.value}'")

    leaderboard_path = leaderboard_dir / f"{new_result.category.value}.json"
    logger.info(f"Using leaderboard file: {leaderboard_path}")

    # Load existing leaderboard
    leaderboard: Leaderboard = Leaderboard.load(leaderboard_path)
    runs: list[EvaluationResultSummary] = list(leaderboard.runs)
    logger.info(f"Loaded {len(runs)} existing runs")

    # Find runs matching this combination
    new_result_key = _get_combination_key(new_result)
    matching_runs: list[EvaluationResultSummary] = [r for r in runs if _get_combination_key(r) == new_result_key]
    other_runs: list[EvaluationResultSummary] = [r for r in runs if _get_combination_key(r) != new_result_key]

    if len(matching_runs) < n:
        logger.info(f"Adding run ({len(matching_runs) + 1}/{n}) for '{new_result.agent_name}' + '{new_result.model}'")
        matching_runs.append(new_result)
    else:
        matching_runs.sort(key=lambda x: x.date)
        logger.info(f"Replacing oldest run (date: {matching_runs[0].date}) for '{new_result.agent_name}' + '{new_result.model}'")
        matching_runs = [*matching_runs[1:], new_result]

    # Combine and rebuild aggregates
    all_runs: list[EvaluationResultSummary] = other_runs + matching_runs
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
):
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
        runs: list[EvaluationResultSummary] = list(leaderboard.runs)

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
