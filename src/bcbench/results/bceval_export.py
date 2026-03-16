"""
Convert the result into a format that bceval can consume and upload to Braintrust.
"""

import json
from pathlib import Path
from typing import Any

from bcbench.dataset import BaseDatasetEntry, get_entry_class
from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)


def write_bceval_results(results: list[BaseEvaluationResult], out_dir: Path, run_id: str, dataset_path: Path, output_filename: str, category: EvaluationCategory) -> None:
    """Write results into a JSONL file for bceval consumption."""
    entry_cls = get_entry_class(category)
    dataset_entries: list[BaseDatasetEntry] = entry_cls.load(dataset_path)

    output_file = out_dir / output_filename
    with open(output_file, "w") as f:
        for result in results:
            matching_entries = [e for e in dataset_entries if e.instance_id == result.instance_id]

            if not matching_entries:
                logger.error(f"No matching dataset entry found for instance_id: {result.instance_id}")
                continue

            matched_entry = matching_entries[0]
            input, expected = matched_entry.get_task(), matched_entry.get_expected_output(result.category)

            metadata: dict[str, Any] = {
                "model": result.model,
                "prompt_tokens": (result.metrics.prompt_tokens if result.metrics else None) or 0,
                "completion_tokens": (result.metrics.completion_tokens if result.metrics else None) or 0,
                "llm_duration": (result.metrics.llm_duration if result.metrics else None) or 0,
                "latency": (result.metrics.execution_time if result.metrics else None) or 0,
                "turn_count": (result.metrics.turn_count if result.metrics else None) or 0,
                "resolved": result.resolved,
                "build": result.build,
                "run_id": run_id,
                "project": result.project,
                "error_message": result.error_message,
                "tool_usage": (result.metrics.tool_usage if result.metrics and result.metrics.tool_usage else None) or 0,
            }

            if isinstance(result, TestGenerationResult):
                metadata["pre_patch_failed"] = result.pre_patch_failed
                metadata["post_patch_passed"] = result.post_patch_passed

            bceval_result = {
                "id": result.instance_id,
                "input": input,
                "expected": expected,
                "output": result.generated_patch,
                "context": "",
                "metadata": metadata,
                "tags": [],
            }
            f.write(json.dumps(bceval_result) + "\n")

    logger.info(f"Wrote bceval results to: {output_file}")
