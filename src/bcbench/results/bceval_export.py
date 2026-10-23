"""
Convert the result into a format that bceval can consume and upload to Braintrust.
"""

import json
import logging
from pathlib import Path
from typing import Any

from bcbench.dataset import BaseDatasetEntry
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.summary import get_benchmark_version
from bcbench.types import BCalPackageProvenance, EvaluationCategory, ExpectedOutput, ExperimentConfiguration

logger = logging.getLogger(__name__)


def _experiment_metadata(
    experiment: ExperimentConfiguration | None,
    bcal_package: BCalPackageProvenance | None,
    git_ref: str | None,
    benchmark_version: str,
) -> dict[str, Any]:
    """Metadata identifying whether a run is a baseline or an experiment, and its configuration.

    bc-eval promotes the ``EvalRunType`` key to the Kusto ``EvalRunType``/``testJobType`` fields
    when ``--eval-run-type`` is left at its default, so no extra CLI flag is needed.
    """
    has_configuration_experiment = experiment is not None and not experiment.is_empty()
    is_experiment: bool = has_configuration_experiment or (bcal_package is not None and bcal_package.is_experiment)
    return {
        "EvalRunType": "experiment" if is_experiment else "baseline",
        "experiment": experiment.model_dump(mode="json") if has_configuration_experiment and experiment else None,
        "git_branch": git_ref,
        "benchmark_version": benchmark_version,
    }


def write_bceval_results(
    results: list[BaseEvaluationResult],
    out_dir: Path,
    run_id: str,
    output_filename: str,
    category: EvaluationCategory,
    git_ref: str | None = None,
) -> None:
    """Write results into a JSONL file for bceval consumption."""
    tiers = {result.tier for result in results}
    if len(tiers) != 1:
        raise ValueError(f"Expected results from a single dataset tier, got: {sorted(tiers)}")
    dataset_entries: list[BaseDatasetEntry] = category.entry_class.load(category.dataset_path(tiers.pop()))
    benchmark_version = get_benchmark_version()

    output_file = out_dir / output_filename
    with output_file.open("w") as f:
        for result in results:
            matching_entries = [e for e in dataset_entries if e.instance_id == result.instance_id]

            if not matching_entries:
                logger.error(f"No matching dataset entry found for instance_id: {result.instance_id}")
                continue

            matched_entry = matching_entries[0]
            task_input: str = matched_entry.get_task()
            expected: ExpectedOutput = matched_entry.get_expected_output()

            metadata: dict[str, Any] = {
                "model": result.model,
                "tier": result.tier,
                "area": matched_entry.metadata.area,
                "family": matched_entry.metadata.family,
                "agent_version": result.agent_version,
                "bcal_package_source": result.bcal_package.source if result.bcal_package else None,
                "bcal_package_branch": result.bcal_package.branch if result.bcal_package else None,
                "bcal_package_feed": result.bcal_package.feed_name if result.bcal_package else None,
                **result.export_metadata,
                "prompt_tokens": (result.metrics.prompt_tokens if result.metrics else None) or 0,
                "completion_tokens": (result.metrics.completion_tokens if result.metrics else None) or 0,
                "llm_duration": (result.metrics.llm_duration if result.metrics else None) or 0,
                "ai_credits": result.metrics.ai_credits if result.metrics else None,
                "latency": (result.metrics.execution_time if result.metrics else None) or 0,
                "turn_count": (result.metrics.turn_count if result.metrics else None) or 0,
                **result.category_metrics,
                "run_id": run_id,
                "project": result.project,
                "error_message": result.error_message,
                "tool_usage": (result.metrics.tool_usage if result.metrics and result.metrics.tool_usage else None) or 0,
                **_experiment_metadata(result.experiment, result.bcal_package, git_ref, benchmark_version),
            }

            bceval_result = {
                "id": result.instance_id,
                "input": task_input,
                "expected": expected,
                "output": result.output,
                "context": "",
                "metadata": metadata,
                "tags": [],
            }
            f.write(json.dumps(bceval_result) + "\n")

    logger.info(f"Wrote bceval results to: {output_file}")
