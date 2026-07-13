"""Model invocation and persistence for the file-path identification task.

This runs a single-shot Copilot CLI call restricted to the ``write`` tool
only — no shell, file-read, or fetch tools — so the model has no way to reach
the target repository or the gold patch on disk. It answers from the bug report
alone (the context-free condition from the SWE-Bench Illusion paper) and its
reply is parsed from stdout. The call runs in an isolated empty working
directory as an extra layer of defense.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from bcbench.config import get_config
from bcbench.contamination.filepath_identification import FilePathIdentificationResult, build_identification_prompt, parse_prediction
from bcbench.copilot_cli import find_copilot
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()

__all__ = ["load_identification_results", "run_filepath_identification", "save_identification_result"]


def _run_copilot_context_free(prompt: str, work_dir: Path, model: str) -> str:
    copilot_cmd = find_copilot()
    if not copilot_cmd:
        raise AgentError("Copilot CLI not found in PATH; cannot run file-path identification")

    # Flatten whitespace so quotes/newlines in the prompt survive CLI arg parsing (mirrors the judge).
    flattened = " ".join(prompt.split())

    completed = subprocess.run(
        [
            copilot_cmd,
            "--silent",  # emit only the agent response on stdout
            "--available-tools=",  # no tools at all: the model must answer as stdout text, and cannot read the repo/gold patch or write its answer to a file
            "--disable-builtin-mcps",
            "--no-custom-instructions",
            f"--model={model}",
            f"--prompt={flattened}",
        ],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_config.timeout.filepath_identification,
        check=True,
    )

    return completed.stdout or ""


def run_filepath_identification(
    entry: BaseDatasetEntry,
    model: str,
    category: str,
    top_k: int,
    output_dir: Path,
) -> FilePathIdentificationResult:
    prompt = build_identification_prompt(entry.get_task(), top_k, repo=entry.repo)

    raw_output = ""
    error: str | None = None
    predicted: list[str] = []

    logger.info("Running context-free file-path identification on %s (model=%s, top_k=%d)", entry.instance_id, model, top_k)
    try:
        with tempfile.TemporaryDirectory(prefix="bcbench-fpid-") as tmp:
            raw_output = _run_copilot_context_free(prompt, Path(tmp), model)
        predicted = parse_prediction(raw_output, top_k)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError, AgentError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("File-path identification failed for %s", entry.instance_id)

    result = FilePathIdentificationResult.build(
        entry=entry,
        model=model,
        category=category,
        top_k=top_k,
        predicted_files=predicted,
        raw_output=raw_output,
        error=error,
    )
    save_identification_result(result, output_dir)
    return result


def save_identification_result(result: FilePathIdentificationResult, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.instance_id}.file-path-identification.jsonl"
    path.write_text(result.model_dump_json() + "\n", encoding="utf-8")
    return path


def load_identification_results(results_dir: Path) -> list[FilePathIdentificationResult]:
    results: list[FilePathIdentificationResult] = []
    for path in sorted(results_dir.rglob("*.file-path-identification.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                results.append(FilePathIdentificationResult.model_validate_json(stripped))
    return results
