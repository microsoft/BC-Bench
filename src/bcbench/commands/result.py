import json
import re
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

import typer

from bcbench.categories.base import CategoryDefinition
from bcbench.cli_options import EvaluationCategoryOption, RunId
from bcbench.commands.composition import build_category_registry, command_context
from bcbench.config import Config
from bcbench.logger import get_logger
from bcbench.results import (
    BaseEvaluationResult,
    EvaluationResultSummary,
    Leaderboard,
    LeaderboardAggregate,
    create_console_summary,
    create_github_job_summary,
    write_bceval_results,
)
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)


result_app = typer.Typer(help="Process and display evaluation results")


@result_app.command("summarize")
def summarize_command(
    ctx: typer.Context,
    run_id: RunId,
    category: EvaluationCategoryOption,
    result_dir: Annotated[Path | None, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)] = None,
    result_pattern: Annotated[str | None, typer.Option(help="Pattern for the per instances result files")] = None,
    summary_output: Annotated[str, typer.Option(help="Output filename for summary JSON")] = "evaluation_summary.json",
    bceval_output: Annotated[str, typer.Option(help="Output filename for bceval results")] = "bceval_results.jsonl",
    git_ref: Annotated[str | None, typer.Option("--git-ref", help="Git ref (branch/tag) the run was dispatched from; recorded in bceval metadata as git_branch")] = None,
) -> None:
    """Summarize evaluation results from a completed run."""
    state = command_context(ctx)
    definition = build_category_registry(state)[category]
    result_dir = result_dir if result_dir is not None else state.config.paths.evaluation_results_path
    result_pattern = result_pattern if result_pattern is not None else f"*{state.config.file_patterns.result_pattern}"
    result_summarize(run_id, definition, result_dir, result_pattern, summary_output, bceval_output, state.config, git_ref)


@result_app.command("update")
def update_command(
    ctx: typer.Context,
    evaluation_summary: Annotated[Path, typer.Argument(help="Path to a single evaluation run's summary JSON", exists=True, file_okay=True, dir_okay=False)],
    leaderboard_dir: Annotated[Path | None, typer.Option(help="Path to the directory containing category-specific leaderboard files")] = None,
    n: Annotated[int, typer.Option(min=1, help="Max number of runs to store per agent+model+experiment combination")] = 5,
) -> None:
    """Update the public leaderboard with a new evaluation summary."""
    state = command_context(ctx)
    leaderboard_dir = leaderboard_dir if leaderboard_dir is not None else state.config.paths.leaderboard_dir
    result_update(evaluation_summary, leaderboard_dir, build_category_registry(state), n)


@result_app.command("refresh")
def refresh_command(
    ctx: typer.Context,
    leaderboard_dir: Annotated[Path | None, typer.Option(help="Path to the directory containing category-specific leaderboard files")] = None,
) -> None:
    """Refresh all leaderboard aggregates without adding new data."""
    state = command_context(ctx)
    leaderboard_dir = leaderboard_dir if leaderboard_dir is not None else state.config.paths.leaderboard_dir
    result_refresh(leaderboard_dir, build_category_registry(state))


def result_summarize(
    run_id: str,
    definition: CategoryDefinition,
    result_dir: Path,
    result_pattern: str,
    summary_output: str,
    bceval_output: str,
    config: Config,
    git_ref: str | None = None,
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
    instance_pattern_regex = re.compile(config.file_patterns.instance_pattern)
    result_files = [f for f in result_files if instance_pattern_regex.match(f.stem)]

    if not result_files:
        logger.error(f"No instance-specific result files found in {run_dir}")
        raise typer.Exit(code=1)

    results: list[BaseEvaluationResult] = []
    for results_path in result_files:
        logger.info(f"Reading results from: {results_path}")
        with results_path.open() as f:
            results.extend(BaseEvaluationResult.from_json(json.loads(line), definition.reporting.result_class) for line in f if line.strip())

    if not results:
        logger.error("No results found in the result files")
        raise typer.Exit(code=1)

    if any(result.category != definition.name for result in results):
        raise ValueError(f"All results must belong to the selected category: {definition.name}")

    entries = definition.entry_class.load(definition.dataset_path)
    write_bceval_results(results, run_dir, run_id, bceval_output, entries, git_ref=git_ref)

    summary = definition.reporting.summary_class.from_results(results, run_id=run_id)

    if config.env.github_actions:
        summary_path = Path(config.env.github_step_summary) if config.env.github_step_summary else None
        create_github_job_summary(results, summary, summary_path)
    else:
        create_console_summary(results, summary)

    summary.save(run_dir, summary_output)


def _rebuild_aggregates(runs: list[EvaluationResultSummary], registry: Mapping[EvaluationCategory, CategoryDefinition]) -> list[LeaderboardAggregate]:
    grouped: defaultdict[tuple[str | None, ...], list[EvaluationResultSummary]] = defaultdict(list)
    for run in runs:
        grouped[(run.category, *run.combination_key())].append(run)
    return [registry[group[0].category].reporting.aggregate_class.from_runs(group) for group in grouped.values()]


def _load_leaderboard(path: Path, registry: Mapping[EvaluationCategory, CategoryDefinition]) -> Leaderboard:
    if not path.exists():
        return Leaderboard(runs=[], aggregate=[])
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not payload:
        return Leaderboard(runs=[], aggregate=[])
    names = {EvaluationCategory(item["category"]) for item in [*payload.get("runs", []), *payload.get("aggregate", [])]}
    definitions = {name: registry[name] for name in names}
    return Leaderboard.load(
        path,
        {name: definition.reporting.summary_class for name, definition in definitions.items()},
        {name: definition.reporting.aggregate_class for name, definition in definitions.items()},
    )


def result_update(
    evaluation_summary: Path,
    leaderboard_dir: Path,
    registry: Mapping[EvaluationCategory, CategoryDefinition],
    n: int = 5,
) -> None:
    """
    Update the public leaderboard with a new evaluation summary.

    Takes a single evaluation run's summary and updates the appropriate category-specific leaderboard file.
    Stores up to n runs per combination, removing the oldest when exceeding n.
    """
    logger.info(f"Loading evaluation summary from: {evaluation_summary}")
    with evaluation_summary.open(encoding="utf-8") as f:
        payload = json.load(f)
        definition = registry[EvaluationCategory(payload["category"])]
        new_result = EvaluationResultSummary.from_json(payload, definition.reporting.summary_class)

    logger.info(f"Processing result for agent '{new_result.agent_name}' with model '{new_result.model}' in category '{new_result.category.value}'")

    leaderboard_path = leaderboard_dir / f"{new_result.category.value}.json"
    logger.info(f"Using leaderboard file: {leaderboard_path}")

    # Load existing leaderboard
    leaderboard: Leaderboard = _load_leaderboard(leaderboard_path, registry)
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
    aggregates = _rebuild_aggregates(all_runs, registry)

    # Write back
    leaderboard = Leaderboard(runs=all_runs, aggregate=aggregates)
    with leaderboard_path.open("w", encoding="utf-8") as f:
        json.dump(leaderboard.to_dict(), f, indent=2)
        f.write("\n")

    logger.info(f"Successfully updated leaderboard at: {leaderboard_path}")


def result_refresh(
    leaderboard_dir: Path,
    registry: Mapping[EvaluationCategory, CategoryDefinition],
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

        leaderboard: Leaderboard = _load_leaderboard(leaderboard_path, registry)
        runs: list[EvaluationResultSummary] = list(leaderboard.runs)

        if not runs:
            logger.warning(f"No runs found in {leaderboard_path.name}, skipping")
            continue

        # Rebuild aggregates from existing runs
        aggregates: list[LeaderboardAggregate] = _rebuild_aggregates(runs, registry)

        # Write back
        leaderboard = Leaderboard(runs=runs, aggregate=aggregates)
        with leaderboard_path.open("w", encoding="utf-8") as f:
            json.dump(leaderboard.to_dict(), f, indent=2)
            f.write("\n")

        logger.info(f"Refreshed {leaderboard_path.name}: {len(runs)} runs -> {len(aggregates)} aggregates")
