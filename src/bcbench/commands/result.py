import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Annotated

import typer

from bcbench.cli_options import EvaluationCategoryOption, OutputDir, RunId
from bcbench.config import get_config
from bcbench.results import (
    BaseEvaluationResult,
    EvaluationResultSummary,
    Leaderboard,
    LeaderboardAggregate,
    create_console_summary,
    create_github_job_summary,
    write_bceval_results,
)
from bcbench.types import NL2ALDataset

logger = logging.getLogger(__name__)


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
    git_ref: Annotated[str | None, typer.Option("--git-ref", help="Git ref (branch/tag) the run was dispatched from; recorded in bceval metadata as git_branch")] = None,
    dataset: Annotated[NL2ALDataset | None, typer.Option(help="Expected NL2AL dataset panel; verifies raw result identity")] = None,
    expected_entries: Annotated[str | None, typer.Option(help="JSON array of selected instance IDs; incomplete or duplicate results block export")] = None,
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
        with results_path.open() as f:
            results.extend(BaseEvaluationResult.from_json(json.loads(line)) for line in f if line.strip())

    if not results:
        logger.error("No results found in the result files")
        raise typer.Exit(code=1)

    if expected_entries is not None:
        _validate_selected_coverage(results, expected_entries, run_dir)

    write_bceval_results(results, run_dir, run_id, bceval_output, category, git_ref=git_ref, dataset=dataset)

    summary = EvaluationResultSummary.from_results(results, run_id=run_id)

    if _config.env.github_actions:
        create_github_job_summary(results, summary)
    else:
        create_console_summary(results, summary)

    summary.save(run_dir, summary_output)


def _validate_selected_coverage(results: list[BaseEvaluationResult], selected_json: str, run_dir: Path) -> None:
    try:
        selected = json.loads(selected_json)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter("expected-entries must be a JSON array of instance IDs") from exc
    if not isinstance(selected, list) or not selected or not all(isinstance(value, str) and value for value in selected):
        raise typer.BadParameter("expected-entries must be a nonempty JSON array of instance IDs")
    expected = set(selected)
    if len(expected) != len(selected):
        raise typer.BadParameter("expected-entries contains duplicate IDs")
    observed = Counter(result.instance_id for result in results)
    coverage = {
        "expected_entry_count": len(expected),
        "produced_entry_count": len(observed),
        "missing_entries": sorted(expected - observed.keys()),
        "unexpected_entries": sorted(observed.keys() - expected),
        "duplicate_entries": sorted(key for key, count in observed.items() if count != 1),
    }
    (run_dir / "evaluation_coverage.json").write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    if coverage["missing_entries"] or coverage["unexpected_entries"] or coverage["duplicate_entries"]:
        logger.error("Selected dataset coverage is incomplete or invalid; refusing scoring upload: %s", coverage)
        raise typer.Exit(code=1)


def _rebuild_aggregates(runs: list[EvaluationResultSummary]) -> list[LeaderboardAggregate]:
    grouped: defaultdict[tuple[str | None, ...], list[EvaluationResultSummary]] = defaultdict(list)
    for run in runs:
        grouped[run.combination_key()].append(run)
    return [group[0].category.aggregate_class.from_runs(group) for group in grouped.values()]


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
    with evaluation_summary.open(encoding="utf-8") as f:
        new_result = EvaluationResultSummary.from_json(json.load(f))

    logger.info(f"Processing result for agent '{new_result.agent_name}' with model '{new_result.model}' in category '{new_result.category.value}'")

    leaderboard_path = leaderboard_dir / f"{new_result.category.value}.json"
    logger.info(f"Using leaderboard file: {leaderboard_path}")

    # Load existing leaderboard
    leaderboard: Leaderboard = Leaderboard.load(leaderboard_path)
    runs: list[EvaluationResultSummary] = list(leaderboard.runs)
    logger.info(f"Loaded {len(runs)} existing runs")

    # Find runs matching this combination
    new_result_key = new_result.combination_key()
    matching_runs: list[EvaluationResultSummary] = [r for r in runs if r.combination_key() == new_result_key]
    other_runs: list[EvaluationResultSummary] = [r for r in runs if r.combination_key() != new_result_key]

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
    with leaderboard_path.open("w", encoding="utf-8") as f:
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
        runs: list[EvaluationResultSummary] = list(leaderboard.runs)

        if not runs:
            logger.warning(f"No runs found in {leaderboard_path.name}, skipping")
            continue

        # Rebuild aggregates from existing runs
        aggregates: list[LeaderboardAggregate] = _rebuild_aggregates(runs)

        # Write back
        leaderboard = Leaderboard(runs=runs, aggregate=aggregates)
        with leaderboard_path.open("w", encoding="utf-8") as f:
            json.dump(leaderboard.to_dict(), f, indent=2)
            f.write("\n")

        logger.info(f"Refreshed {leaderboard_path.name}: {len(runs)} runs -> {len(aggregates)} aggregates")
