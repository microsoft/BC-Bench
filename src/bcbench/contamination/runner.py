"""Run and persist the filepath identification probe."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from bcbench_core.agent.copilot import CopilotHarness
from bcbench_core.agent.harness import AgentRequest, AgentResult

from bcbench.collection.patch_utils import extract_file_paths_from_patch
from bcbench.contamination.filepath_identification import (
    FilePathIdentificationResult,
    build_identification_prompt,
    matches_any_gold_path,
    parse_prediction,
)
from bcbench.dataset import BugFixEntry
from bcbench.results.base import RESULT_FILE_SUFFIX
from bcbench.types import AgentHarness, EvaluationCategory

logger = logging.getLogger(__name__)

_RESULT_SUFFIX = f".filepath-identification{RESULT_FILE_SUFFIX}"


def run_filepath_identification(entry: BugFixEntry, model: str, result_dir: Path, timeout: int = 15 * 60) -> FilePathIdentificationResult:
    task = entry.get_task()
    prompt: str = build_identification_prompt(task, repo=entry.repo)

    logger.info("Running context-free filepath identification on %s (model=%s)", entry.instance_id, model)
    with tempfile.TemporaryDirectory(prefix="bcbench-fpid-") as tmp:
        result: AgentResult = CopilotHarness(name=AgentHarness.COPILOT, model=model, env=os.environ, timeout=timeout).run(AgentRequest(task=prompt, work_dir=Path(tmp), output_dir=Path(tmp) / "logs"))
    metrics, raw_output = result.metrics, result.response or ""

    gold_files: list[str] = extract_file_paths_from_patch(entry.patch)
    try:
        predicted_files: list[str] = parse_prediction(raw_output)
    except ValueError:
        logger.exception("Failed to parse filepath identification response for %s. Raw output:\n%s", entry.instance_id, raw_output)
        raise

    file_identification_result = FilePathIdentificationResult(
        instance_id=entry.instance_id,
        model=model,
        category=EvaluationCategory.BUG_FIX,
        gold_files=gold_files,
        predicted_files=predicted_files,
        matches_any_gold_path=matches_any_gold_path(predicted_files, gold_files),
        metrics=metrics,
        raw_output=raw_output,
    )
    save_identification_result(file_identification_result, result_dir)
    return file_identification_result


def save_identification_result(result: FilePathIdentificationResult, result_dir: Path) -> Path:
    path = result_dir / f"{result.instance_id}{_RESULT_SUFFIX}"
    path.write_text(result.model_dump_json() + "\n", encoding="utf-8")
    return path


def load_identification_results(results_dir: Path) -> list[FilePathIdentificationResult]:
    return [FilePathIdentificationResult.model_validate_json(path.read_text(encoding="utf-8")) for path in sorted(results_dir.rglob(f"*{_RESULT_SUFFIX}"))]
