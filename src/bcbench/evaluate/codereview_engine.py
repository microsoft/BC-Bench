"""BC PR-Review engine runner for the code-review category (faithful convergence arm).

Instead of BC-Bench's own review pipeline, this runner invokes the engine's
self-contained local-review entry point (``Invoke-LocalReview.ps1`` from
``microsoft/BC-ALAgents``), which filters a BCQuality checkout and runs the
exact production reviewer against the patched worktree. BC-Bench then normalizes
the engine's ``_review-report.json`` into the ``review.json`` shape its scorer
already understands.
"""

import base64
import json
import os
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
REVIEW_REPORT_FILE_NAME = "_review-report.json"
REVIEW_OUTPUT_FILE = "review.json"
BCQUALITY_REPO_URL = "https://github.com/microsoft/BCQuality.git"
_ENGINE_TIMEOUT_SECONDS = 1800

# BCQuality emits blocker/major/minor/info; the engine and BC-Bench gold use
# Critical/High/Medium/Low. Mirror the production engine's map
# (Invoke-CopilotPRReview.ps1: blocker=Critical, major=High, minor=Medium, info=Low).
_SEVERITY_MAP = {"blocker": "critical", "major": "high", "minor": "medium", "info": "low"}


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


def _prepare_bcquality(work_dir: Path) -> Path:
    """Provide a disposable BCQuality checkout for the engine.

    Invoke-LocalReview.ps1 requires -BCQualityRoot and its filter step DELETES files
    in place, so we never point it at a live clone. Prefer a caller-provided checkout
    (copied minus .git); otherwise clone microsoft/BCQuality at BCQUALITY_REF.
    """
    dest = work_dir / "bcquality"
    if dest.exists():
        shutil.rmtree(dest)

    local = os.environ.get("BCQUALITY_ROOT")
    if local:
        shutil.copytree(local, dest, ignore=shutil.ignore_patterns(".git"))
        return dest

    ref = os.environ.get("BCQUALITY_REF") or "main"
    token = (
        os.environ.get("BCQUALITY_REPO_TOKEN")
        or os.environ.get("ENGINE_REPO_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
    )
    auth: list[str] = []
    if token:
        # Pass the token via an auth header (like actions/checkout) so it never
        # lands in the remote URL or any error message.
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        auth = ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]

    logger.info(f"Cloning BCQuality @ {ref}")
    clone = subprocess.run(
        ["git", *auth, "clone", "--quiet", BCQUALITY_REPO_URL, str(dest)],
        cwd=work_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if clone.returncode != 0:
        raise AgentError(f"Failed to clone BCQuality: {clone.stderr.strip()}")
    checkout = subprocess.run(
        ["git", "-C", str(dest), "checkout", "--quiet", ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if checkout.returncode != 0:
        raise AgentError(f"Failed to checkout BCQuality ref '{ref}': {checkout.stderr.strip()}")
    return dest


def _run_local_review(
    local_review_script: Path,
    repo_path: Path,
    bcquality_root: Path,
    engine_output_dir: Path,
    base_ref: str,
    model: str,
) -> None:
    # Invoke-LocalReview.ps1 filters the given BCQuality checkout and runs the production
    # reviewer, reading GH_TOKEN from the inherited env for Copilot CLI auth.
    args = [
        _pwsh(),
        "-NoProfile",
        "-File",
        str(local_review_script),
        "-RepoPath",
        str(repo_path),
        "-BaseRef",
        base_ref,
        "-BCQualityRoot",
        str(bcquality_root),
        "-OutputDir",
        str(engine_output_dir),
    ]
    if model:
        args += ["-Model", model]
    logger.info(f"Invoking PR-review engine: {local_review_script}")
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=_ENGINE_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AgentTimeoutError(f"PR-review engine timed out after {_ENGINE_TIMEOUT_SECONDS}s") from exc
    if result.stdout:
        logger.info(result.stdout)
    if result.returncode != 0:
        raise AgentError(f"PR-review engine failed (exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}")


def _finding_to_comment(finding: dict) -> dict | None:
    location = finding.get("location") or {}
    file_path = location.get("file")
    line_range = location.get("range") or {}
    line_start = location.get("line") or line_range.get("start-line")
    body = (finding.get("message") or "").strip()
    if not file_path or not line_start or not body:
        return None
    comment: dict = {"file": file_path, "line_start": line_start, "body": body}
    line_end = line_range.get("end-line")
    if line_end:
        comment["line_end"] = line_end
    severity = finding.get("severity")
    if severity:
        comment["severity"] = _SEVERITY_MAP.get(str(severity).lower(), str(severity).lower())
    return comment


def _findings_to_review_comments(payload: dict) -> list[dict]:
    comments: list[dict] = []
    for finding in payload.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        comment = _finding_to_comment(finding)
        if comment is not None:
            comments.append(comment)
    return comments


def _write_review_json(engine_output_dir: Path, repo_path: Path) -> int:
    report_file = engine_output_dir / REVIEW_REPORT_FILE_NAME
    if not report_file.exists():
        raise AgentError(f"Engine did not produce {REVIEW_REPORT_FILE_NAME} at {engine_output_dir}")
    payload = json.loads(report_file.read_text(encoding="utf-8"))
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

    bcquality_root = _prepare_bcquality(output_dir)
    base_ref = _commit_patched_worktree(repo_path)

    started_at = time.monotonic()
    _run_local_review(local_review_script, repo_path, bcquality_root, engine_output_dir, base_ref, model)
    execution_time = time.monotonic() - started_at

    _write_review_json(engine_output_dir, repo_path)

    metrics = AgentMetrics(execution_time=execution_time)
    experiment = ExperimentConfiguration(custom_agent="bc-pr-review-engine")
    return metrics, experiment
