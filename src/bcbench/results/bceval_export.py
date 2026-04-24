"""
Convert the result into a format that bceval can consume and upload to Braintrust.
"""

import json
from pathlib import Path
from typing import Any

from bcbench.dataset import BaseDatasetEntry
from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# POC: LMChecklist integration
# ---------------------------------------------------------------------------
# These assertions are a proof-of-concept showing how bc-eval's LmChecklist
# scorer can be layered on top of an existing bug-fix run. In a real checklist
# category (e.g. code-review) assertions would come from the dataset entry;
# here they are hardcoded so we can demonstrate the end-to-end flow against
# the existing bug-fix pipeline without changing its semantics.
#
# LmChecklist expects `expected` to be a dict with an "assertions" key. We
# wrap the dataset's original `expected` under a "patch" key and attach the
# assertions alongside. Existing execution-based evaluators (ResolutionRate,
# BuildRate) read from `metadata`, not `expected`, so this wrapping is safe.
_POC_BUGFIX_CHECKLIST_ASSERTIONS: list[dict[str, str]] = [
    {
        "text": "The generated patch does not disable, delete, or skip any existing tests.",
        "level": "critical",
    },
    {
        "text": "The generated patch does not contain TODO/FIXME comments or commented-out code.",
        "level": "expected",
    },
]


def write_bceval_results(
    results: list[BaseEvaluationResult],
    out_dir: Path,
    run_id: str,
    output_filename: str,
    category: EvaluationCategory,
    include_poc_checklist: bool = False,
) -> None:
    """Write results into a JSONL file for bceval consumption.

    Args:
        include_poc_checklist: POC flag. When True, wraps `expected` as a dict
            containing both the dataset's original expected value and a
            hardcoded set of checklist assertions so bc-eval's LmChecklist
            scorer can be run over the same file. Off by default to preserve
            today's execution-based behaviour.
    """
    entry_cls = category.entry_class
    dataset_entries: list[BaseDatasetEntry] = entry_cls.load(category.dataset_path)

    output_file = out_dir / output_filename
    with open(output_file, "w") as f:
        for result in results:
            matching_entries = [e for e in dataset_entries if e.instance_id == result.instance_id]

            if not matching_entries:
                logger.error(f"No matching dataset entry found for instance_id: {result.instance_id}")
                continue

            matched_entry = matching_entries[0]
            input, expected = matched_entry.get_task(), matched_entry.get_expected_output()

            if include_poc_checklist:
                expected = {
                    "patch": expected,
                    "assertions": _POC_BUGFIX_CHECKLIST_ASSERTIONS,
                }

            metadata: dict[str, Any] = {
                "model": result.model,
                "prompt_tokens": (result.metrics.prompt_tokens if result.metrics else None) or 0,
                "completion_tokens": (result.metrics.completion_tokens if result.metrics else None) or 0,
                "llm_duration": (result.metrics.llm_duration if result.metrics else None) or 0,
                "latency": (result.metrics.execution_time if result.metrics else None) or 0,
                "turn_count": (result.metrics.turn_count if result.metrics else None) or 0,
                **result.category_metrics,
                "run_id": run_id,
                "project": result.project,
                "error_message": result.error_message,
                "tool_usage": (result.metrics.tool_usage if result.metrics and result.metrics.tool_usage else None) or 0,
            }

            bceval_result = {
                "id": result.instance_id,
                "input": input,
                "expected": expected,
                "output": result.output,
                "context": "",
                "metadata": metadata,
                "tags": [],
            }
            f.write(json.dumps(bceval_result) + "\n")

    logger.info(f"Wrote bceval results to: {output_file}")
