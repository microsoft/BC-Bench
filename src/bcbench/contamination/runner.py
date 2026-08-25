"""Run and persist the filepath identification probe."""

from __future__ import annotations

import tempfile
from pathlib import Path

from bcbench.agent.copilot.cli import invoke_copilot
from bcbench.collection.patch_utils import extract_file_paths_from_patch
from bcbench.config import get_config
from bcbench.contamination.filepath_identification import (
    FilePathIdentificationResult,
    build_identification_prompt,
    matches_any_gold_path,
    parse_prediction,
)
from bcbench.dataset import BugFixEntry
from bcbench.logger import get_logger
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)
_config = get_config()

_RESULT_SUFFIX = f".filepath-identification{_config.file_patterns.result_pattern}"


def run_filepath_identification(entry: BugFixEntry, model: str, result_dir: Path) -> FilePathIdentificationResult:
    task = entry.get_task()
    prompt: str = build_identification_prompt(task, repo=entry.repo)

    logger.info("Running context-free filepath identification on %s (model=%s)", entry.instance_id, model)
    with tempfile.TemporaryDirectory(prefix="bcbench-fpid-") as tmp:
        metrics, raw_output = invoke_copilot(
            prompt=prompt,
            model=model,
            work_dir=Path(tmp),
            timeout=_config.timeout.filepath_identification,
        )

    gold_files: list[str] = extract_file_paths_from_patch(entry.patch)
    predicted_files: list[str] = parse_prediction(raw_output)

    result = FilePathIdentificationResult(
        instance_id=entry.instance_id,
        model=model,
        category=EvaluationCategory.BUG_FIX,
        gold_files=gold_files,
        predicted_files=predicted_files,
        matches_any_gold_path=matches_any_gold_path(predicted_files, gold_files),
        metrics=metrics,
        raw_output=raw_output,
    )
    save_identification_result(result, result_dir)
    return result


def save_identification_result(result: FilePathIdentificationResult, result_dir: Path) -> Path:
    path = result_dir / f"{result.instance_id}{_RESULT_SUFFIX}"
    path.write_text(result.model_dump_json() + "\n", encoding="utf-8")
    return path


def load_identification_results(results_dir: Path) -> list[FilePathIdentificationResult]:
    return [FilePathIdentificationResult.model_validate_json(path.read_text(encoding="utf-8")) for path in sorted(results_dir.rglob(f"*{_RESULT_SUFFIX}"))]
