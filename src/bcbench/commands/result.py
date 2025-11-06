import json
from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.cli_options import OutputDir, RunId
from bcbench.config import get_config
from bcbench.logger import get_logger
from bcbench.results import create_console_summary, create_github_job_summary
from bcbench.results.evaluation_result import EvaluationResult, EvaluationResultSummary

logger = get_logger(__name__)
_config = get_config()

result_app = typer.Typer(help="Process and display evaluation results")


@result_app.command("summarize")
def result_summarize(
    run_id: RunId,
    result_dir: OutputDir = _config.paths.evaluation_results_path,
    result_pattern: Annotated[str, typer.Option(help="Pattern for the result files")] = "*.jsonl",
):
    """
    Summarize evaluation results from a completed run.

    Example:
        bcbench result summarize mini_test_run
    """
    run_dir: Path = result_dir / run_id

    if not run_dir.exists():
        logger.error(f"Results directory not found: {run_dir}")
        raise typer.Exit(code=1)

    result_files = list(run_dir.rglob(result_pattern))
    if not result_files:
        logger.error(f"No result files matching '{result_pattern}' found in {run_dir}")
        raise typer.Exit(code=1)

    results: list[EvaluationResult] = []
    for results_path in result_files:
        logger.info(f"Reading results from: {results_path}")
        with open(results_path) as f:
            results.extend(EvaluationResult.from_json(json.loads(line)) for line in f if line.strip())

    if not results:
        logger.error("No results found in the result files")
        raise typer.Exit(code=1)

    if _config.env.github_actions:
        create_github_job_summary(results)
    else:
        create_console_summary(results)

    summary = EvaluationResultSummary.from_results(results, run_id=run_id)
    summary.save(run_dir)
