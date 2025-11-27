import json
import re
from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.cli_options import DatasetPath, OutputDir, RunId
from bcbench.config import get_config
from bcbench.logger import get_logger
from bcbench.results import BaseEvaluationResult, EvaluationResultSummary, create_console_summary, create_github_job_summary, create_result_from_json, write_bceval_results
from bcbench.types import ExperimentConfiguration

logger = get_logger(__name__)


def _experiments_equal(exp1: ExperimentConfiguration | None, exp2: ExperimentConfiguration | None) -> bool:
    """Compare two experiment configurations, treating None as equivalent to an empty config.

    This handles the case where JSON has "experiment": null but the pipeline creates
    an ExperimentConfiguration with all default values.
    """
    # Normalize None to empty config for comparison
    exp1_normalized = exp1 if exp1 is not None and not exp1.is_empty() else None
    exp2_normalized = exp2 if exp2 is not None and not exp2.is_empty() else None
    return exp1_normalized == exp2_normalized


_config = get_config()

result_app = typer.Typer(help="Process and display evaluation results")


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


@result_app.command("update")
def result_update(
    evaluation_summary: Annotated[Path, typer.Argument(help="Path to a single evaluation run's summary JSON", exists=True, file_okay=True, dir_okay=False)],
    leaderboard_dir: Annotated[Path, typer.Option(help="Path to the directory containing category-specific leaderboard files")] = _config.paths.leaderboard_dir,
):
    """
    Update the public leaderboard with a new evaluation summary.

    Takes a single evaluation run's summary and updates the appropriate category-specific
    leaderboard file (e.g. bug-fix.json), either replacing an existing
    agent-model combination or adding a new entry.

    Example:
        bcbench result update evaluation_results/12345/evaluation_summary.json
    """
    logger.info(f"Loading evaluation summary from: {evaluation_summary}")
    with open(evaluation_summary, encoding="utf-8") as f:
        new_result = EvaluationResultSummary.model_validate_json(f.read())

    logger.info(f"Processing result for agent '{new_result.agent_name}' with model '{new_result.model}' in category '{new_result.category.value}'")

    # Determine the appropriate leaderboard file based on category
    leaderboard_path = leaderboard_dir / f"{new_result.category.value}.json"

    logger.info(f"Using leaderboard file: {leaderboard_path}")

    # Load or create leaderboard file
    if leaderboard_path.exists():
        logger.info(f"Loading existing leaderboard from: {leaderboard_path}")
        with open(leaderboard_path, encoding="utf-8") as f:
            existing_results: list[EvaluationResultSummary] = [EvaluationResultSummary.model_validate(entry) for entry in json.load(f)]
    else:
        logger.info(f"Creating new leaderboard file: {leaderboard_path}")
        existing_results = []

    # Check if result already exists for this agent+model+experiment combination
    updated = False
    for i, result in enumerate(existing_results):
        if result.agent_name == new_result.agent_name and result.model == new_result.model and _experiments_equal(result.experiment, new_result.experiment):
            logger.info(f"Found existing result for '{new_result.agent_name}' + '{new_result.model}', replacing...")
            existing_results[i] = new_result
            updated = True
            break

    if not updated:
        logger.info(f"No existing result found for '{new_result.agent_name}' + '{new_result.model}', adding new entry")
        existing_results.append(new_result)

    # Write back as list of dicts
    with open(leaderboard_path, "w", encoding="utf-8") as f:
        json.dump([result.to_dict() for result in existing_results], f, indent=2)
        f.write("\n")

    logger.info(f"Successfully updated leaderboard at: {leaderboard_path}")
