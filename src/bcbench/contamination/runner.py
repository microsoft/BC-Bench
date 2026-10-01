"""Run and persist the filepath identification probe."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from bcbench.agent.copilot.cli import invoke_copilot
from bcbench.agent.settings import AgentSettings
from bcbench.collection.patch_utils import extract_file_paths_from_patch
from bcbench.config import Config
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


def run_filepath_identification(entry: BugFixEntry, model: str, result_dir: Path, config: Config, settings: AgentSettings) -> FilePathIdentificationResult:
    task = entry.get_task()
    prompt: str = build_identification_prompt(task, repo=entry.repo)

    logger.info("Running context-free filepath identification on %s (model=%s)", entry.instance_id, model)
    workspace = result_dir / f".filepath-identification-{uuid.uuid4().hex}"
    workspace.mkdir(parents=True)
    try:
        metrics, raw_output = invoke_copilot(
            prompt=prompt,
            model=model,
            work_dir=workspace,
            timeout=config.timeout.filepath_identification,
            executable=settings.copilot_executable,
            env=settings.environment,
            allow_all_tools=False,
        )
    finally:
        shutil.rmtree(workspace)

    gold_files: list[str] = extract_file_paths_from_patch(entry.patch)
    try:
        predicted_files: list[str] = parse_prediction(raw_output)
    except ValueError:
        logger.exception("Failed to parse filepath identification response for %s. Raw output:\n%s", entry.instance_id, raw_output)
        raise

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
    save_identification_result(result, result_dir, config.file_patterns.result_pattern)
    return result


def save_identification_result(result: FilePathIdentificationResult, result_dir: Path, result_suffix: str) -> Path:
    path = result_dir / f"{result.instance_id}.filepath-identification{result_suffix}"
    path.write_text(result.model_dump_json() + "\n", encoding="utf-8")
    return path


def load_identification_results(results_dir: Path, result_suffix: str) -> list[FilePathIdentificationResult]:
    return [FilePathIdentificationResult.model_validate_json(path.read_text(encoding="utf-8")) for path in sorted(results_dir.rglob(f"*.filepath-identification{result_suffix}"))]
