"""BC PR-Review engine runner for the code-review category (faithful convergence arm).

Instead of BC-Bench's own review pipeline, this runner invokes the engine's
self-contained local-review entry point (``Invoke-LocalReview.ps1`` from
``microsoft/BC-ALReviewAgent``), which fetches+filters BCQuality and runs the
exact production reviewer against the patched worktree. BC-Bench then normalizes
the engine's ``al-code-review-findings.json`` into the ``review.json`` shape its
scorer already understands.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, ExperimentConfiguration

logger = get_logger(__name__)

LOCAL_REVIEW_SCRIPT_NAME = "Invoke-LocalReview.ps1"
FINDINGS_FILE_NAME = "al-code-review-findings.json"
REVIEW_OUTPUT_FILE = "review.json"
_ENGINE_TIMEOUT_SECONDS = 1800


def _pwsh() -> str:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise AgentError("pwsh (PowerShell 7+) is required to run the PR-review engine but was not found on PATH")
    return pwsh


def _git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo_path, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AgentError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _commit_patched_worktree(repo_path: Path) -> str:
    base_ref = _git(repo_path, "rev-parse", "HEAD")
    _git(repo_path, "add", "-A")
    _git(
        repo_path,
        "-c",
        "user.name=bcbench",
        "-c",
        "user.email=bcbench@local",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--allow-empty",
        "-m",
        "bcbench: apply dataset patch for local review",
    )
    return base_ref


def _run_local_review(
    local_review_script: Path,
    repo_path: Path,
    engine_output_dir: Path,
    base_ref: str,
    model: str,
) -> None:
    # Invoke-LocalReview.ps1 self-contains fetch+filter+run and reads GH_TOKEN and the optional
    # BCQUALITY_REF override from the inherited env (via the engine's Get-BCQualityConfig).
    args = [
        _pwsh(),
        "-NoProfile",
        "-File",
        str(local_review_script),
        "-Workspace",
        str(repo_path),
        "-BaseRef",
        base_ref,
        "-OutputDir",
        str(engine_output_dir),
        "-Model",
        model,
    ]
    logger.info(f"Invoking PR-review engine: {local_review_script}")
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=_ENGINE_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AgentTimeoutError(f"PR-review engine timed out after {_ENGINE_TIMEOUT_SECONDS}s") from exc
    if result.stdout:
        logger.info(result.stdout)
    if result.returncode != 0:
        raise AgentError(f"PR-review engine failed (exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}")


def _findings_to_review_comments(payload: dict) -> list[dict]:
    comments: list[dict] = []
    for finding in payload.get("findings") or []:
        file_path = finding.get("filePath")
        line = finding.get("lineNumber")
        if not file_path or not line:
            continue
        issue = (finding.get("issue") or "").strip()
        recommendation = (finding.get("recommendation") or "").strip()
        body = (f"{issue}\n\nRecommendation: {recommendation}" if issue else recommendation) if recommendation else issue
        comment: dict = {"file": file_path, "line_start": line, "body": body}
        severity = finding.get("severity")
        if severity:
            comment["severity"] = str(severity).lower()
        comments.append(comment)
    return comments


def _write_review_json(review_output_dir: Path, repo_path: Path) -> int:
    findings_file = review_output_dir / FINDINGS_FILE_NAME
    if not findings_file.exists():
        raise AgentError(f"Engine did not produce {FINDINGS_FILE_NAME} at {review_output_dir}")
    payload = json.loads(findings_file.read_text(encoding="utf-8"))
    comments = _findings_to_review_comments(payload)
    (repo_path / REVIEW_OUTPUT_FILE).write_text(json.dumps(comments, indent=2), encoding="utf-8")
    logger.info(f"Wrote {len(comments)} review comment(s) to {repo_path / REVIEW_OUTPUT_FILE}")
    return len(comments)


def run_engine_review(
    entry: BaseDatasetEntry,
    model: str,
    repo_path: Path,
    output_dir: Path,
    engine_scripts_dir: Path,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    local_review_script = engine_scripts_dir / LOCAL_REVIEW_SCRIPT_NAME
    if not local_review_script.exists():
        raise AgentError(f"Engine script not found: {local_review_script}")

    logger.info(f"Running PR-review engine on: {entry.instance_id}")

    output_dir.mkdir(parents=True, exist_ok=True)
    engine_output_dir = output_dir / "engine-output"

    base_ref = _commit_patched_worktree(repo_path)

    started_at = time.monotonic()
    _run_local_review(local_review_script, repo_path, engine_output_dir, base_ref, model)
    execution_time = time.monotonic() - started_at

    _write_review_json(engine_output_dir / "review-output", repo_path)

    metrics = AgentMetrics(execution_time=execution_time)
    experiment = ExperimentConfiguration(custom_agent="bc-pr-review-engine")
    return metrics, experiment
