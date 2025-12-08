import json
from pathlib import Path

from bcbench.dataset import DatasetEntry, load_dataset_entries
from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)

# TODO: handle test-generation category


def write_bceval_results(results: list[BaseEvaluationResult], out_dir: Path, run_id: str, dataset_path: Path, output_filename: str) -> None:
    """Write results into a JSONL file for bceval consumption."""
    dataset_entries: list[DatasetEntry] = load_dataset_entries(dataset_path)

    output_file = out_dir / output_filename
    with open(output_file, "w") as f:
        for result in results:
            matching_entries = [e for e in dataset_entries if e.instance_id == result.instance_id]

            if not matching_entries:
                logger.error(f"No matching dataset entry found for instance_id: {result.instance_id}")
                continue

            input, expected = get_info_from_dataset_entry(matching_entries[0], result.category)

            bceval_result = {
                "id": result.instance_id,
                "input": input,
                "expected": expected,
                "output": result.generated_patch,
                "context": "",
                "metadata": {
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
                    "tool_usage": (result.metrics.tool_usage if result.metrics and result.metrics.tool_usage else None) or 0,
                },
                "tags": [],
            }
            f.write(json.dumps(bceval_result) + "\n")

    logger.info(f"Wrote bceval results to: {output_file}")


def get_info_from_dataset_entry(entry: DatasetEntry, category: EvaluationCategory) -> tuple[str, str]:
    """
    Extract relevant info from DatasetEntry for bceval results.

    Args:
        entry: The DatasetEntry instance
        category: The evaluation category
    Returns:
        A tuple of (input, expected output)
    """
    match category:
        case EvaluationCategory.BUG_FIX:
            return entry.get_task(), entry.patch
        case EvaluationCategory.TEST_GENERATION:
            return entry.get_task(), entry.test_patch
        case _:
            raise ValueError(f"Unsupported evaluation category: {category}")
