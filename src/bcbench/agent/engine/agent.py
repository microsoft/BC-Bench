"""BC PR-Review engine agent runner (faithful convergence arm).

Instead of BC-Bench's own review pipeline, this runner invokes the exact
production reviewer script (``Invoke-CopilotPRReview.ps1`` from
``microsoft/BC-ALReviewAgent``) in its local review mode against the
patched worktree, then normalizes the engine's ``al-code-review-findings.json``
into the ``review.json`` shape BC-Bench's scorer already understands.
"""

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

FETCH_BCQUALITY_SCRIPT = Path(__file__).parent / "fetch_bcquality.ps1"
FINDINGS_FILE_NAME = "al-code-review-findings.json"
REVIEW_OUTPUT_FILE = "review.json"
_ENGINE_TIMEOUT_SECONDS = 1800


def _pwsh() -> str:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise AgentError("pwsh (PowerShell 7+) is required to run the PR-review engine but was not found on PATH")
    return pwsh


def _resolve_token(gh_token: str | None) -> str:
    token = gh_token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    gh = shutil.which("gh")
    if gh:
        result = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise AgentError("No GitHub/Copilot token available. Set GH_TOKEN (or GITHUB_TOKEN), or run 'gh auth login'.")


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


def _fetch_bcquality(
    engine_scripts_dir: Path,
    bcquality_root: Path,
    config_path: Path | None,
    bcquality_repo: str | None = None,
    bcquality_ref: str | None = None,
) -> str:
    args = [
        _pwsh(),
        "-NoProfile",
        "-File",
        str(FETCH_BCQUALITY_SCRIPT),
        "-EngineScriptsDir",
        str(engine_scripts_dir),
        "-BCQualityRoot",
        str(bcquality_root),
    ]
    if config_path:
        args += ["-ConfigPath", str(config_path)]
    # BCQUALITY_REPO/REF override the baseline config's repo+ref (the engine's
    # Get-BCQualityConfig honours these env vars), so a CI run can point at a
    # modified BCQuality branch/SHA without editing the engine.
    env = {**os.environ}
    if bcquality_repo:
        env["BCQUALITY_REPO"] = bcquality_repo
    if bcquality_ref:
        env["BCQUALITY_REF"] = bcquality_ref
    result = subprocess.run(args, capture_output=True, text=True, timeout=_ENGINE_TIMEOUT_SECONDS, env=env, check=False)
    if result.returncode != 0:
        raise AgentError(f"BCQuality fetch/filter failed: {result.stderr.strip() or result.stdout.strip()}")
    sha = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
    if not sha:
        raise AgentError("BCQuality fetch/filter did not return a resolved SHA")
    logger.info(f"BCQuality cloned+filtered at {sha}")
    return sha


def _run_engine(
    engine_script: Path,
    repo_path: Path,
    review_output_dir: Path,
    base_ref: str,
    bcquality_root: Path,
    bcquality_sha: str,
    model: str,
    token: str,
) -> None:
    env = {
        **os.environ,
        "REVIEW_SOURCE": "local",
        "REVIEW_PHASE": "all",
        "BASE_REF": base_ref,
        "BASE_BRANCH": "main",
        "REVIEW_WORKSPACE": str(repo_path),
        "REVIEW_TARGET_WORKSPACE": str(repo_path),
        "REVIEW_OUTPUT_DIR": str(review_output_dir),
        "BCQUALITY_ROOT": str(bcquality_root),
        "BCQUALITY_SHA": bcquality_sha,
        "GH_TOKEN": token,
        "GITHUB_REPOSITORY": "local/bcbench",
        "COPILOT_MODEL": model,
    }
    args = [_pwsh(), "-NoProfile", "-File", str(engine_script)]
    logger.info(f"Invoking PR-review engine: {engine_script}")
    try:
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=_ENGINE_TIMEOUT_SECONDS, check=False)
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
        domain = finding.get("domain")
        if domain:
            comment["domain"] = domain
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
    config_path: Path | None = None,
    gh_token: str | None = None,
    bcquality_repo: str | None = None,
    bcquality_ref: str | None = None,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    engine_script = engine_scripts_dir / "Invoke-CopilotPRReview.ps1"
    if not engine_script.exists():
        raise AgentError(f"Engine script not found: {engine_script}")

    logger.info(f"Running PR-review engine on: {entry.instance_id}")
    token = _resolve_token(gh_token)

    output_dir.mkdir(parents=True, exist_ok=True)
    review_output_dir = output_dir / "review-output"
    review_output_dir.mkdir(parents=True, exist_ok=True)
    bcquality_root = output_dir / "bcquality"

    base_ref = _commit_patched_worktree(repo_path)
    bcquality_sha = _fetch_bcquality(engine_scripts_dir, bcquality_root, config_path, bcquality_repo, bcquality_ref)

    started_at = time.monotonic()
    _run_engine(engine_script, repo_path, review_output_dir, base_ref, bcquality_root, bcquality_sha, model, token)
    execution_time = time.monotonic() - started_at

    _write_review_json(review_output_dir, repo_path)

    metrics = AgentMetrics(execution_time=execution_time)
    experiment = ExperimentConfiguration(custom_agent="bc-pr-review-engine")
    return metrics, experiment
