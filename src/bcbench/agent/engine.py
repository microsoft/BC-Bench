"""BC PR-Review engine runner for the code-review category (faithful convergence arm).

Instead of BC-Bench's own review pipeline, this runner invokes the engine's
self-contained local-review entry point (``Invoke-LocalReview.ps1`` from
``microsoft/BC-ALAgents``), which filters a BCQuality checkout and runs the
exact production reviewer against the patched worktree.

The entry point writes the agent's raw report to ``<OutputDir>/_review-report.json``
(and run stats to ``_run-metrics.json``). BC-Bench normalizes that report into the
flat ``review.json`` its scorer understands. Note this scores the raw agent report;
the full production flow's later post-processing (dedup, volume caps, placement) is
not represented, so this arm measures the reviewer's findings, not the posted set.

The engine is pinned to a released tag (``_DEFAULT_ENGINE_REF``, override ENGINE_REF) so
BCQuality content stays the only variable under test: point the arm at a BCQuality fork,
branch, or local checkout (``BCQUALITY_REPO`` / ``BCQUALITY_REF`` / ``BCQUALITY_ROOT``) to
measure how a BCQuality change moves the score.
"""

import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from bcbench.dataset import BaseDatasetEntry
from bcbench.dataset.codereview import Severity
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, ExperimentConfiguration

logger = get_logger(__name__)

LOCAL_REVIEW_SCRIPT_NAME = "Invoke-LocalReview.ps1"
REVIEW_REPORT_FILE_NAME = "_review-report.json"
RUN_METRICS_FILE_NAME = "_run-metrics.json"
REVIEW_OUTPUT_FILE = "review.json"
BCQUALITY_REPO_URL = "https://github.com/microsoft/BCQuality.git"
ENGINE_REPO_URL = "https://github.com/microsoft/BC-ALAgents.git"
# The engine's local-review scripts live here inside microsoft/BC-ALAgents.
ENGINE_SCRIPTS_SUBPATH = "agents/ALReviewAgent/scripts"
# Pin a released engine tag by default so BCQuality content is the only variable under
# test; a floating "latest" would let a mid-experiment engine release skew an A/B. Override
# with ENGINE_REF. The exact commit reviewed is still recorded per run via engine_ref.
# 1.19.4 is the first tag that carries the BCQUALITY_CONSUME=plugin path this arm relies on.
_DEFAULT_ENGINE_REF = "1.20.4"
_ENGINE_TIMEOUT_SECONDS = 1800


def _pwsh() -> str:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise AgentError("pwsh (PowerShell 7+) is required to run the PR-review engine but was not found on PATH")
    return pwsh


def _first_env(*names: str) -> str | None:
    """Return the first non-empty value among the given environment variables."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def code_review_uses_engine() -> bool:
    """Whether the code-review category routes through the BC PR-Review engine arm.

    This arm defaults to the engine, so activation lives in code (not the workflow):
    dispatching on this branch runs the engine without any workflow env. Set
    BCBENCH_CODE_REVIEW_AGENT=copilot to run the plain Copilot reviewer instead (A/B).
    """
    return os.environ.get("BCBENCH_CODE_REVIEW_AGENT", "engine").strip().lower() != "copilot"


def _git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo_path, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AgentError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_head(path: Path) -> str | None:
    """Resolve the HEAD commit of a checkout, or None if it is not a git repo."""
    try:
        result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


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


def _bcquality_repo_url() -> str:
    """Resolve the BCQuality repo to review with, honoring the BCQUALITY_REPO override.

    Accepts a full clone URL or a bare ``owner/repo`` (assumed on github.com), so a
    CI run can point the arm at a fork without editing the engine.
    """
    repo = os.environ.get("BCQUALITY_REPO")
    if not repo:
        return BCQUALITY_REPO_URL
    if repo.startswith(("http://", "https://", "git@")):
        return repo
    return f"https://github.com/{repo}.git"


def _engine_repo_url() -> str:
    """Resolve the engine repo to clone, honoring the ENGINE_REPO override.

    Accepts a full clone URL or a bare ``owner/repo`` (assumed on github.com), mirroring
    _bcquality_repo_url so the arm can target a fork without editing the workflow.
    """
    repo = os.environ.get("ENGINE_REPO")
    if not repo:
        return ENGINE_REPO_URL
    if repo.startswith(("http://", "https://", "git@")):
        return repo
    return f"https://github.com/{repo}.git"


def _clone_at_ref(url: str, ref: str, dest: Path, token: str | None) -> str | None:
    """Clone ``url`` into ``dest``, check out ``ref``, and return the resolved SHA.

    When a token is present it is passed via an http.extraheader (like actions/checkout)
    so it never lands in the remote URL or an error message; public repos clone with no
    token. Returns the checked-out commit for reproducibility.
    """
    auth: list[str] = []
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        auth = ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]
    clone = subprocess.run(["git", *auth, "clone", "--quiet", url, str(dest)], capture_output=True, text=True, check=False)
    if clone.returncode != 0:
        raise AgentError(f"Failed to clone {url}: {clone.stderr.strip()}")
    checkout = subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", ref], capture_output=True, text=True, check=False)
    if checkout.returncode != 0:
        raise AgentError(f"Failed to checkout '{ref}' from {url}: {checkout.stderr.strip()}")
    return _git_head(dest)


def _prepare_bcquality(work_dir: Path) -> tuple[Path, str | None]:
    """Provide a disposable BCQuality checkout for the engine and its resolved commit.

    Invoke-LocalReview.ps1 requires -BCQualityRoot and its filter step DELETES files
    in place, so we never point it at a live clone. Prefer a caller-provided checkout
    (copied minus .git); otherwise clone microsoft/BCQuality (or BCQUALITY_REPO) at
    BCQUALITY_REF. Returns the checkout path and the resolved BCQuality SHA (for
    reproducibility), or None when the source is not a git repo.
    """
    dest = work_dir / "bcquality"
    if dest.exists():
        shutil.rmtree(dest)

    local = os.environ.get("BCQUALITY_ROOT")
    if local:
        shutil.copytree(local, dest, ignore=shutil.ignore_patterns(".git"))
        return dest, _git_head(Path(local))

    url = _bcquality_repo_url()
    ref = os.environ.get("BCQUALITY_REF") or "main"
    token = _first_env("BCQUALITY_REPO_TOKEN", "ENGINE_REPO_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
    logger.info(f"Cloning BCQuality @ {ref}")
    return dest, _clone_at_ref(url, ref, dest, token)


def _prepare_engine(work_dir: Path, engine_scripts_dir: Path | None) -> tuple[Path, str | None]:
    """Provide the engine's agent/scripts directory and its resolved commit.

    Prefer a caller/env-provided local checkout (``--engine-scripts-dir`` / ENGINE_SCRIPTS_DIR)
    for local dev; otherwise clone microsoft/BC-ALAgents (or ENGINE_REPO) at ENGINE_REF
    (default a pinned release tag, see _DEFAULT_ENGINE_REF) and use its agent/scripts subdir.
    The exact commit reviewed is returned for reproducibility.
    """
    if engine_scripts_dir is not None:
        return engine_scripts_dir, _git_head(engine_scripts_dir)

    dest = work_dir / "engine"
    if dest.exists():
        shutil.rmtree(dest)
    url = _engine_repo_url()
    ref = os.environ.get("ENGINE_REF") or _DEFAULT_ENGINE_REF
    token = _first_env("ENGINE_REPO_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
    logger.info(f"Cloning PR-review engine @ {ref}")
    sha = _clone_at_ref(url, ref, dest, token)
    return dest / ENGINE_SCRIPTS_SUBPATH, sha


def _ensure_powershell_yaml() -> None:
    """Ensure the engine's YAML dependency is installed (Get-BCQualityConfig throws without it)."""
    check = subprocess.run(
        [_pwsh(), "-NoProfile", "-Command", "if (Get-Module -ListAvailable -Name powershell-yaml) { exit 0 } exit 1"],
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode == 0:
        return
    logger.info("Installing powershell-yaml for the engine arm")
    install = subprocess.run(
        [
            _pwsh(),
            "-NoProfile",
            "-Command",
            "Set-PSRepository PSGallery -InstallationPolicy Trusted; Install-Module powershell-yaml -Scope CurrentUser -Force",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if install.returncode != 0:
        raise AgentError(f"Failed to install powershell-yaml: {install.stderr.strip() or install.stdout.strip()}")


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
    # The engine's Copilot CLI authenticates via GH_TOKEN; bridge it from the tokens the
    # generic workflow already exposes (COPILOT_GITHUB_TOKEN / GITHUB_TOKEN) so the arm
    # needs no extra workflow env.
    env = os.environ.copy()
    if not env.get("GH_TOKEN"):
        bridged = env.get("COPILOT_GITHUB_TOKEN") or env.get("GITHUB_TOKEN")
        if bridged:
            env["GH_TOKEN"] = bridged
    # Clone-only credentials were already consumed by _prepare_engine/_prepare_bcquality;
    # drop them so they are never inherited by the reviewer subprocess (only GH_TOKEN remains).
    for clone_only in ("BCQUALITY_REPO_TOKEN", "ENGINE_REPO_TOKEN"):
        env.pop(clone_only, None)
    # Consume BCQuality as a Copilot CLI plugin (--plugin-dir) rather than a CWD checkout.
    # The engine's own default is 'cwd'; a caller can still force cwd by presetting the env.
    env.setdefault("BCQUALITY_CONSUME", "plugin")
    logger.info(f"Invoking PR-review engine ({env['BCQUALITY_CONSUME']} mode): {local_review_script}")
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=_ENGINE_TIMEOUT_SECONDS, check=False, env=env)
    except subprocess.TimeoutExpired as exc:
        raise AgentTimeoutError(f"PR-review engine timed out after {_ENGINE_TIMEOUT_SECONDS}s") from exc
    if result.stdout:
        logger.info(result.stdout)
    if result.returncode != 0:
        raise AgentError(f"PR-review engine failed (exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}")


def _map_severity(value: str) -> str:
    """Map a finding's severity to the shared gold taxonomy (one table for every arm).

    Reuses Severity.from_input so blocker/major/minor/info and the canonical
    critical/high/medium/low resolve exactly as the scorer parses gold; an unrecognized
    value passes through lowercased instead of failing the run.
    """
    try:
        return Severity.from_input(value).value
    except ValueError:
        return value.strip().lower()


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
        comment["severity"] = _map_severity(str(severity))
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


def _loads_review_report(text: str) -> dict:
    """Parse the engine report, tolerating shell-escaped single quotes.

    When a finding's ``suggested-code`` carries AL Label text emitted through a
    single-quoted shell argument, the POSIX close/escape/reopen idiom ``'\\''``
    can leak into ``_review-report.json``. That 4-char sequence is invalid JSON
    and breaks ``json.loads``. Collapsing it back to a bare ``'`` is safe (the
    sequence can never appear in well-formed JSON). Recent engine builds already
    normalize this on disk (microsoft/BC-ALAgents ``Repair-ShellEscapedQuotes``);
    this guard keeps the arm robust when pinned to an older engine tag.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        repaired = text.replace("'\\''", "'")
        if repaired == text:
            raise
        return json.loads(repaired)


def _write_review_json(engine_output_dir: Path, repo_path: Path) -> int:
    report_file = engine_output_dir / REVIEW_REPORT_FILE_NAME
    if not report_file.exists():
        raise AgentError(f"Engine did not produce {REVIEW_REPORT_FILE_NAME} at {engine_output_dir}")
    payload = _loads_review_report(report_file.read_text(encoding="utf-8"))
    comments = _findings_to_review_comments(payload)
    (repo_path / REVIEW_OUTPUT_FILE).write_text(json.dumps(comments, indent=2), encoding="utf-8")
    logger.info(f"Wrote {len(comments)} review comment(s) to {repo_path / REVIEW_OUTPUT_FILE}")
    return len(comments)


def _read_run_metrics(engine_output_dir: Path) -> dict:
    """Read the engine's _run-metrics.json (token/timing stats), or {} if absent."""
    metrics_file = engine_output_dir / RUN_METRICS_FILE_NAME
    if not metrics_file.exists():
        return {}
    try:
        return json.loads(metrics_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def run_engine_review(
    entry: BaseDatasetEntry,
    model: str,
    repo_path: Path,
    output_dir: Path,
    engine_scripts_dir: Path | None = None,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    logger.info(f"Running PR-review engine on: {entry.instance_id}")

    output_dir.mkdir(parents=True, exist_ok=True)
    engine_output_dir = output_dir / "engine-output"

    engine_scripts_dir, engine_ref = _prepare_engine(output_dir, engine_scripts_dir)
    local_review_script = engine_scripts_dir / LOCAL_REVIEW_SCRIPT_NAME
    if not local_review_script.exists():
        raise AgentError(f"Engine script not found: {local_review_script}")

    _ensure_powershell_yaml()
    bcquality_root, bcquality_sha = _prepare_bcquality(output_dir)
    base_ref = _commit_patched_worktree(repo_path)

    started_at = time.monotonic()
    _run_local_review(local_review_script, repo_path, bcquality_root, engine_output_dir, base_ref, model)
    execution_time = time.monotonic() - started_at

    _write_review_json(engine_output_dir, repo_path)

    raw_metrics = _read_run_metrics(engine_output_dir)
    metrics = AgentMetrics(
        execution_time=execution_time,
        prompt_tokens=raw_metrics.get("prompt_tokens"),
        completion_tokens=raw_metrics.get("completion_tokens"),
    )
    experiment = ExperimentConfiguration(
        custom_agent="bc-pr-review-engine",
        engine_ref=engine_ref,
        bcquality_sha=bcquality_sha,
    )
    return metrics, experiment
