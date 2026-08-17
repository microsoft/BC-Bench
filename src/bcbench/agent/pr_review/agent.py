"""Run the BC-ALAgents review engine (generate half) as a BC-Bench agent.

The code-review category runs the engine's own generate shell
(``Invoke-PRReviewShell.ps1 -GenerateOnly``) in local mode against the entry's changes,
so BC-Bench measures the real PROD engine + BCQuality rather than a divergent
re-implementation. The BC-Bench ``--model`` threads straight through to the single
Copilot the engine spawns (``COPILOT_MODEL``).

The engine writes ``agent-output.txt`` (the harvested findings report); we map it to
``review.json`` in the repo root so the existing code-review scorer runs unchanged.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from bcbench.agent.pr_review.review_output import engine_report_to_review_comments, load_engine_report
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, EvaluationCategory, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()

_AGENT_OUTPUT_FILE = "agent-output.txt"
_REVIEW_OUTPUT_FILE = "review.json"
_PREPARE_BCQUALITY_SCRIPT = Path(__file__).parent / "scripts" / "Prepare-BCQualityRoot.ps1"


def _load_pr_review_settings() -> dict[str, Any]:
    config_file = _config.paths.agent_share_dir / "config.yaml"
    data = yaml.safe_load(config_file.read_text()) or {}
    return data.get("pr_review") or {}


def _resolve_pr_review_root(settings: dict[str, Any]) -> Path:
    raw = os.environ.get("BC_PR_REVIEW_ROOT") or settings.get("path")
    if not raw:
        raise AgentError("Engine root not configured. Set 'pr_review.path' in the shared agent config.yaml or the BC_PR_REVIEW_ROOT environment variable.")
    root = Path(raw).expanduser()
    shell = root / "agents" / "ALReviewAgent" / "scripts" / "Invoke-PRReviewShell.ps1"
    if not shell.exists():
        raise AgentError(f"Engine review shell not found at {shell}. Check 'pr_review.path' points at a BC-ALAgents checkout.")
    return root


def _resolve_engine_revision(engine_root: Path) -> str:
    """Resolve the engine checkout's git revision (with a dirty marker) for provenance."""
    head = subprocess.run(["git", "-C", str(engine_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    if head.returncode != 0 or not head.stdout.strip():
        return "unknown"
    sha = head.stdout.strip()
    dirty = subprocess.run(["git", "-C", str(engine_root), "status", "--porcelain"], capture_output=True, text=True, check=False)
    if dirty.returncode == 0 and dirty.stdout.strip():
        return f"{sha}-dirty"
    return sha


def _resolve_pwsh() -> str:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise AgentError("PowerShell (pwsh) not found in PATH. The BC-ALAgents engine requires PowerShell 7+.")
    return pwsh


def _resolve_gh_token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    gh = shutil.which("gh")
    if gh:
        result = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise AgentError("No GitHub token available for Copilot CLI auth. Set GH_TOKEN or run `gh auth login`.")


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def _commit_patch_as_head(repo_path: Path) -> None:
    """Commit the applied working-tree patch so the engine can diff base..HEAD.

    The code-review pipeline applies the entry patch as uncommitted changes (and
    marks new files intent-to-add). The engine's local mode diffs a committed
    ``BASE_REF...HEAD`` range, so materialize the changes as a head commit on top
    of the base commit (which is the current HEAD).
    """
    _git(["add", "-A"], repo_path)
    status = _git(["status", "--porcelain"], repo_path)
    if not status.stdout.strip():
        raise AgentError("No changes to review: the entry patch produced an empty working tree diff.")
    _git(
        ["-c", "user.name=bcbench", "-c", "user.email=bcbench@local", "commit", "-q", "--no-verify", "-m", "bcbench review head"],
        repo_path,
    )


def _init_trusted_workspace(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], path)
    _git(["-c", "user.name=bcbench", "-c", "user.email=bcbench@local", "commit", "-q", "--allow-empty", "-m", "trusted"], path)
    return path


def _prepare_bcquality_root(
    engine_root: Path,
    pwsh: str,
    dest: Path,
    bcquality_ref: str | None,
    bcquality_repo: str | None = None,
    bcquality_local_path: str | None = None,
) -> tuple[Path, str | None]:
    env = {**os.environ}
    if bcquality_repo:
        env["BCQUALITY_REPO"] = bcquality_repo
    if bcquality_ref:
        env["BCQUALITY_REF"] = bcquality_ref
    args = [pwsh, "-NoProfile", "-File", str(_PREPARE_BCQUALITY_SCRIPT), "-EngineRoot", str(engine_root), "-Root", str(dest)]
    if bcquality_local_path:
        args += ["-LocalPath", bcquality_local_path]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        logger.error(f"BCQuality preparation failed:\n{result.stdout}\n{result.stderr}")
        raise AgentError(f"Failed to prepare BCQuality root (exit {result.returncode}).")
    root: Path | None = None
    sha: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith("root="):
            root = Path(line[len("root=") :].strip())
        elif line.startswith("sha="):
            sha = line[len("sha=") :].strip()
    if root is None or not root.exists():
        raise AgentError("BCQuality preparation did not report a valid root.")
    return root, sha


def _write_review_json(output_dir: Path, repo_path: Path) -> int:
    agent_output = output_dir / _AGENT_OUTPUT_FILE
    if not agent_output.exists():
        raise AgentError(f"Engine did not produce {_AGENT_OUTPUT_FILE} in {output_dir}.")
    report = load_engine_report(agent_output.read_text(encoding="utf-8"))
    if report is None:
        raise AgentError(f"Engine {_AGENT_OUTPUT_FILE} was empty or not a valid findings report; refusing to score it as a clean review.")
    if not isinstance(report.get("findings"), list):
        raise AgentError(f"Engine report in {_AGENT_OUTPUT_FILE} has no findings list (got {type(report.get('findings')).__name__}); refusing to score it as a clean review.")
    comments = engine_report_to_review_comments(report)
    (repo_path / _REVIEW_OUTPUT_FILE).write_text(json.dumps(comments, indent=2), encoding="utf-8")
    return len(comments)


def run_pr_review_agent(
    entry: BaseDatasetEntry,
    model: str,
    category: EvaluationCategory,
    repo_path: Path,
    output_dir: Path,
    bcquality_ref: str | None = None,
    bcquality_repo: str | None = None,
    bcquality_local_path: str | None = None,
    min_severity: str | None = None,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run the engine's generate half on a code-review entry and write review.json.

    Separate from run_copilot_agent by design: this spawns the PROD BC-ALAgents
    PowerShell orchestrator (Copilot is spawned inside the engine, not here), so it
    owns none of the copilot-harness prompt/MCP/LSP wiring and takes engine-specific
    inputs (BCQuality source, min severity) for the code-review category only.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration).
    """
    if category is not EvaluationCategory.CODE_REVIEW:
        raise AgentError(f"The engine agent only supports the code-review category, got {category.value}.")
    if not isinstance(entry, CodeReviewEntry):
        raise AgentError(f"The engine agent requires a CodeReviewEntry, got {type(entry).__name__}.")

    settings = _load_pr_review_settings()
    engine_root = _resolve_pr_review_root(settings)
    pwsh = _resolve_pwsh()
    gh_token = _resolve_gh_token()
    agent_version = str(settings.get("agent_version", "0.0.0"))
    severity = min_severity or settings.get("min_severity") or "Low"
    bcquality_cfg = settings.get("bcquality") or {}
    bcquality_repo = bcquality_repo or bcquality_cfg.get("repo")
    bcquality_ref = bcquality_ref or bcquality_cfg.get("ref")
    bcquality_local_path = bcquality_local_path or bcquality_cfg.get("local_path")

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Running BC-ALAgents review engine on: {entry.instance_id}")

    _commit_patch_as_head(repo_path)
    trusted_workspace = _init_trusted_workspace(output_dir / "trusted")
    bcquality_root, bcquality_sha = _prepare_bcquality_root(
        engine_root,
        pwsh,
        output_dir / "bcquality",
        bcquality_ref,
        bcquality_repo,
        bcquality_local_path,
    )

    shell = engine_root / "agents" / "ALReviewAgent" / "scripts" / "Invoke-PRReviewShell.ps1"
    env = {
        **os.environ,
        "REVIEW_SOURCE": "local",
        "BASE_REF": entry.base_commit,
        "REVIEW_TARGET_WORKSPACE": str(repo_path),
        "REVIEW_WORKSPACE": str(trusted_workspace),
        "REVIEW_OUTPUT_DIR": str(output_dir),
        "BCQUALITY_ROOT": str(bcquality_root),
        "COPILOT_MODEL": model,
        "COPILOT_REVIEW_AGENT_VERSION": agent_version,
        "AGENT_MINIMUM_SEVERITY": severity,
        "GH_TOKEN": gh_token,
    }

    plugins = [f"bc-review-engine@{_resolve_engine_revision(engine_root)}"]
    if bcquality_sha:
        plugins.append(f"BCQuality@{bcquality_sha}")
    config = ExperimentConfiguration(
        custom_agent="bc-review-engine",
        plugins=plugins,
    )

    start = time.monotonic()
    try:
        result = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(shell), "-GenerateOnly", "-OutputDir", str(output_dir)],
            cwd=str(repo_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=_config.timeout.agent_execution,
            check=True,
        )
        logger.debug(f"Engine stdout:\n{result.stdout}")
        if result.stderr:
            logger.debug(f"Engine stderr:\n{result.stderr}")
        count = _write_review_json(output_dir, repo_path)
        logger.info(f"Engine review complete for {entry.instance_id}: wrote {count} comment(s) to {_REVIEW_OUTPUT_FILE}")
    except subprocess.TimeoutExpired:
        logger.exception(f"Engine review timed out after {_config.timeout.agent_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
        raise AgentTimeoutError("Engine review timed out", metrics=metrics, config=config) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"Engine review failed (exit {e.returncode}):\n{e.stdout}\n{e.stderr}")
        raise AgentError(f"Engine review execution failed: {e}") from None
    except Exception:
        logger.exception("Unexpected error running engine review")
        raise
    else:
        return AgentMetrics(execution_time=time.monotonic() - start), config
