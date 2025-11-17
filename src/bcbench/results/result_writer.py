import json
from pathlib import Path

from bcbench.dataset import DatasetEntry, load_dataset_entries
from bcbench.logger import get_logger
from bcbench.results.evaluation_result import EvaluationResult

logger = get_logger(__name__)


def write_bceval_results(results: list[EvaluationResult], out_dir: Path, run_id: str, dataset_path: Path, output_filename: str) -> None:
    """Write results into a JSONL file for bceval consumption."""
    dataset_entries: list[DatasetEntry] = load_dataset_entries(dataset_path)

    output_file = out_dir / output_filename
    with open(output_file, "w") as f:
        for result in results:
            matching_entries = [e for e in dataset_entries if e.instance_id == result.instance_id]

            if not matching_entries:
                logger.error(f"No matching dataset entry found for instance_id: {result.instance_id}")
                continue

            dataset_entry: DatasetEntry = matching_entries[0]

            bceval_result = {
                "id": result.instance_id,
                "input": dataset_entry.get_task(),
                "expected": dataset_entry.patch,
                "output": result.generated_patch,
                "context": "",
                "metadata": {
                    "model": result.model,
                    "prompt_tokens": result.prompt_tokens or 0,
                    "completion_tokens": result.completion_tokens or 0,
                    "latency": result.agent_execution_time or 0,
                    "resolved": result.resolved,
                    "build": result.build,
                    "run_id": run_id,
                    "project": result.project,
                },
                "tags": [],
            }
            f.write(json.dumps(bceval_result) + "\n")

    logger.info(f"Wrote bceval results to: {output_file}")
