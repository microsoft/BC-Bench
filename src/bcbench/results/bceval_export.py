"""
Convert the result into a format that bceval can consume and upload to Braintrust.
"""

import json
import logging
from hashlib import sha256
from pathlib import Path
from typing import Any

from bcbench.dataset import BaseDatasetEntry, NL2ALEntry
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.summary import get_benchmark_version
from bcbench.types import BCalPackageProvenance, EvaluationCategory, ExpectedOutput, ExperimentConfiguration, NL2ALDataset

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
    dataset: NL2ALDataset | None = None,
) -> None:
    """Write results into a JSONL file for bceval consumption."""
    entry_cls = category.entry_class
    category.dataset_path_for(dataset)
    entry_cache: dict[NL2ALDataset | None, list[BaseDatasetEntry]] = {}
    hash_cache: dict[NL2ALDataset, str] = {}
    benchmark_version = get_benchmark_version()
    rows: list[dict[str, Any]] = []

    for result in results:
        panel = result.dataset if category is EvaluationCategory.NL2AL else None

        if dataset is not None:
            if result.dataset is None:
                raise ValueError(f"Result {result.instance_id} is missing recorded dataset identity")
            if result.dataset != dataset:
                raise ValueError(f"Result {result.instance_id} dataset {result.dataset!r} does not match selected dataset {dataset}")
            panel = dataset

        if panel is not None and (result.dataset_version is None or result.dataset_sha256 is None):
            raise ValueError(f"Result {result.instance_id} is missing recorded dataset version/hash")

        if panel not in entry_cache:
            dataset_path = category.dataset_path_for(panel)
            entry_cache[panel] = entry_cls.load(dataset_path)
            if panel is not None:
                hash_cache[panel] = sha256(dataset_path.read_bytes()).hexdigest()

        if panel is not None:
            if result.dataset_sha256 != hash_cache[panel]:
                raise ValueError(f"Dataset hash changed for {result.instance_id}; refusing to score against different assertions")
            if result.dataset_version != panel.version:
                raise ValueError(f"Dataset version mismatch for {result.instance_id}")

        matching_entries = [entry for entry in entry_cache[panel] if entry.instance_id == result.instance_id]

        if not matching_entries:
            if panel is not None:
                raise ValueError(f"No entry {result.instance_id} in selected dataset {panel}")
            logger.error(f"No matching dataset entry found for instance_id: {result.instance_id}")
            continue

        matched_entry = matching_entries[0]
        dataset_metadata: dict[str, Any] = {}
        tags: list[str] = []
        if panel is not None:
            if not isinstance(matched_entry, NL2ALEntry):
                raise TypeError(f"Selected NL2AL dataset returned {type(matched_entry).__name__}")

            dataset_metadata = {
                "dataset": panel.value,
                "dataset_version": result.dataset_version,
                "dataset_sha256": hash_cache[panel],
                "dataset_mode": "single_turn",
                "dataset_turn_count": 1,
                "evaluation_scope": "single_turn",
                "area": matched_entry.metadata.area,
                "family": matched_entry.metadata.family,
                "scenario_tier": matched_entry.metadata.tier,
            }
            tags = [
                f"dataset-{panel.value}",
                f"dataset-version-{panel.version}",
                "dataset-mode-single-turn",
                "evaluation-scope-single-turn",
                *(
                    f"{name}-{value}"
                    for name, value in (
                        ("area", matched_entry.metadata.area),
                        ("family", matched_entry.metadata.family),
                        ("tier", matched_entry.metadata.tier),
                    )
                    if value
                ),
            ]

        task_input: str = matched_entry.get_task()
        expected: ExpectedOutput = matched_entry.get_expected_output()

        metadata: dict[str, Any] = {
            "model": result.model,
            "agent_version": result.agent_version,
            "bcal_package_source": result.bcal_package.source if result.bcal_package else None,
            "bcal_package_branch": result.bcal_package.branch if result.bcal_package else None,
            "bcal_package_feed": result.bcal_package.feed_name if result.bcal_package else None,
            "cohort_name": result.cohort_name,
            "cohort_sha256": result.cohort_sha256,
            "repetition_index": result.repetition_index,
            "repetition_count": result.repetition_count,
            **result.export_metadata,
            **dataset_metadata,
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

        rows.append(
            {
                "id": result.instance_id,
                "input": task_input,
                "expected": expected,
                "output": result.output,
                "context": result.evidence if result.evidence is not None else "",
                "metadata": metadata,
                "tags": tags,
            }
        )

    output_file = out_dir / output_filename
    with output_file.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row) + "\n")

    logger.info(f"Wrote bceval results to: {output_file}")
