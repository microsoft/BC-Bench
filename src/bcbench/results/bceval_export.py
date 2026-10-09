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
from bcbench.types import EvaluationCategory, ExpectedOutput, ExperimentConfiguration, NL2ALDataset

logger = logging.getLogger(__name__)


def _experiment_metadata(experiment: ExperimentConfiguration | None, git_ref: str | None, benchmark_version: str) -> dict[str, Any]:
    """Metadata identifying whether a run is a baseline or an experiment, and its configuration.

    bc-eval promotes the ``EvalRunType`` key to the Kusto ``EvalRunType``/``testJobType`` fields
    when ``--eval-run-type`` is left at its default, so no extra CLI flag is needed.
    """
    is_experiment: bool = experiment is not None and not experiment.is_empty()
    return {
        "EvalRunType": "experiment" if is_experiment else "baseline",
        "experiment": experiment.model_dump(mode="json") if is_experiment and experiment else None,
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

    output_file = out_dir / output_filename
    with output_file.open("w", encoding="utf-8") as f:
        for result in results:
            panel = (result.dataset or dataset) if category is EvaluationCategory.NL2AL else None
            if dataset is not None and result.dataset != dataset:
                raise ValueError(f"Result {result.instance_id} dataset {result.dataset!r} does not match selected dataset {dataset}")
            if panel is not None and (result.dataset_sha256 is None or result.dataset_version is None):
                raise ValueError(f"Result {result.instance_id} is missing recorded dataset version/hash")
            if panel not in entry_cache:
                path = category.dataset_path_for(panel)
                entry_cache[panel] = entry_cls.load(path)
                if panel is not None:
                    hash_cache[panel] = sha256(path.read_bytes()).hexdigest()
            dataset_entries = entry_cache[panel]
            if panel is not None:
                if result.dataset_sha256 is not None and result.dataset_sha256 != hash_cache[panel]:
                    raise ValueError(f"Dataset hash changed for {result.instance_id}; refusing to score against different assertions")
                if result.dataset_version is not None and result.dataset_version != panel.version:
                    raise ValueError(f"Dataset version mismatch for {result.instance_id}")
            matching_entries = [e for e in dataset_entries if e.instance_id == result.instance_id]

            if not matching_entries:
                if panel is not None:
                    raise ValueError(f"No entry {result.instance_id} in selected dataset {panel}")
                logger.error(f"No matching dataset entry found for instance_id: {result.instance_id}")
                continue

            matched_entry = matching_entries[0]
            dataset_metadata: dict[str, Any] = {}
            tags: list[str] = []
            if panel is not None and isinstance(matched_entry, NL2ALEntry):
                if bool(matched_entry.turns) != (panel is NL2ALDataset.MULTITURN):
                    raise ValueError(f"Entry {result.instance_id} turn structure does not match dataset {panel}")
                dataset_metadata = {
                    "dataset": panel.value,
                    "dataset_version": result.dataset_version or panel.version,
                    "dataset_sha256": hash_cache[panel],
                    "dataset_mode": "multiturn" if matched_entry.turns else "single_turn",
                    "dataset_turn_count": len(matched_entry.turns) or 1,
                    "evaluation_scope": "final_artifact" if matched_entry.turns else "single_turn",
                    "area": matched_entry.metadata.area,
                    "family": matched_entry.metadata.family,
                    "scenario_tier": matched_entry.metadata.tier,
                }
                tags = [f"dataset-{panel.value}", f"dataset-version-{panel.version}"]
            task_input: str = matched_entry.get_task()
            expected: ExpectedOutput = matched_entry.get_expected_output()

            metadata: dict[str, Any] = {
                "model": result.model,
                "agent_version": result.agent_version,
                "timeout": result.timeout,
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
                **_experiment_metadata(result.experiment, git_ref, benchmark_version),
            }

            bceval_result = {
                "id": result.instance_id,
                "input": task_input,
                "expected": expected,
                "output": result.output,
                "context": "",
                "metadata": metadata,
                "tags": tags,
            }
            f.write(json.dumps(bceval_result) + "\n")

    logger.info(f"Wrote bceval results to: {output_file}")
