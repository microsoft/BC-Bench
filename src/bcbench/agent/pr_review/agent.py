"""Run the BC-ALAgents review engine as a BC-Bench agent.

The code-review category runs the production orchestrator in local mode against the
entry's changes. Local mode executes the complete generation, parsing, filtering, and
artifact pipeline but returns before posting, so BC-Bench measures the real production
engine + BCQuality rather than a divergent re-implementation. The BC-Bench ``--model``
threads straight through to the Copilot process the engine spawns (``COPILOT_MODEL``).

The engine writes normalized findings to ``al-code-review-findings.json``; we map them
to ``review.json`` in the repo root so the existing code-review scorer runs unchanged.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from bcbench.agent.copilot.metrics import parse_metrics
from bcbench.agent.pr_review.review_output import engine_report_to_review_comments, load_engine_report
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.operations import commit_changes, get_repository_revision, has_changes, init_repo
from bcbench.types import AgentMetrics, EvaluationCategory, ExecutionProvenance, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()

_FINDINGS_OUTPUT_FILE = "al-code-review-findings.json"
_REVIEW_OUTPUT_FILE = "review.json"
_PREPARE_BCQUALITY_SCRIPT = Path(__file__).parent / "scripts" / "Prepare-BCQualityRoot.ps1"
_IGNORED_BCQUALITY_ARTIFACTS = {
    "_filter-report.json",
    "_run-metrics.json",
    "_task-context.json",
}


def _load_pr_review_settings() -> dict[str, Any]:
    config_file = _config.paths.agent_share_dir / "config.yaml"
    return yaml.safe_load(config_file.read_text(encoding="utf-8"))["pr_review"]


def _resolve_pr_review_root(settings: dict[str, Any]) -> Path:
    raw = os.environ.get("BC_PR_REVIEW_ROOT") or settings["path"]
    if not raw:
        raise AgentError("Engine root not configured. Set 'pr_review.path' in the shared agent config.yaml or the BC_PR_REVIEW_ROOT environment variable.")
    root = Path(raw).expanduser().resolve()
    engine = root / "agents" / "ALReviewAgent" / "scripts" / "Invoke-CopilotPRReview.ps1"
    if not engine.exists():
        raise AgentError(f"Engine orchestrator not found at {engine}. Check 'pr_review.path' points at a BC-ALAgents checkout.")
    return root


def _resolve_pwsh() -> str:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise AgentError("PowerShell (pwsh) not found in PATH. The BC-ALAgents engine requires PowerShell 7+.")
    return pwsh


def _commit_patch_as_head(repo_path: Path) -> None:
    """Commit the applied working-tree patch so the engine can diff base..HEAD.

    The code-review pipeline applies the entry patch as uncommitted changes (and
    marks new files intent-to-add). The engine's local mode diffs a committed
    ``BASE_REF...HEAD`` range, so materialize the changes as a head commit on top
    of the base commit (which is the current HEAD).
    """
    if not has_changes(repo_path):
        raise AgentError("No changes to review: the entry patch produced an empty working tree diff.")
    commit_changes(repo_path, "bcbench review head", no_verify=True)


def _init_trusted_workspace(path: Path) -> Path:
    init_repo(path)
    commit_changes(path, "trusted", allow_empty=True)
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
        encoding="utf-8",
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


def _bcquality_content_digest(root: Path) -> str:
    digest = hashlib.sha256()

    def is_included(path: Path) -> bool:
        relative = path.relative_to(root)
        if ".git" in relative.parts or not path.is_file():
            return False
        return len(relative.parts) > 1 or (path.name not in _IGNORED_BCQUALITY_ARTIFACTS and not path.name.startswith("_review-"))

    files = sorted(
        filter(is_included, root.rglob("*")),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def _build_experiment_configuration(
    engine_root: Path,
    bcquality_root: Path,
    bcquality_sha: str | None,
    custom_bcquality: bool,
) -> ExperimentConfiguration:
    if not bcquality_sha:
        raise AgentError("BCQuality preparation did not report its resolved revision.")
    knowledge_base = f"BCQuality@{bcquality_sha}+content.{_bcquality_content_digest(bcquality_root)}"
    return ExperimentConfiguration(
        knowledge_base=knowledge_base if custom_bcquality else None,
        provenance=ExecutionProvenance(
            agent_harness=f"BC-ALAgents@{get_repository_revision(engine_root)}",
            knowledge_base=knowledge_base,
        ),
    )


def _write_review_json(output_dir: Path, repo_path: Path) -> int:
    findings_output = output_dir / _FINDINGS_OUTPUT_FILE
    if not findings_output.exists():
        raise AgentError(f"Engine did not produce {_FINDINGS_OUTPUT_FILE} in {output_dir}.")
    report = load_engine_report(findings_output.read_text(encoding="utf-8"))
    if report is None:
        raise AgentError(f"Engine {_FINDINGS_OUTPUT_FILE} was empty or invalid; refusing to score it as a clean review.")
    outcome = report.get("outcome")
    if outcome == "failed":
        reason = report.get("outcomeReason") or "unknown reason"
        raise AgentError(f"Engine review failed: {reason}")
    if outcome not in {"completed", "partial", "not-applicable", "no-knowledge"}:
        raise AgentError(f"Engine {_FINDINGS_OUTPUT_FILE} has unsupported outcome {outcome!r}.")
    if not isinstance(report.get("findings"), list):
        raise AgentError(f"Engine report in {_FINDINGS_OUTPUT_FILE} has no findings list (got {type(report.get('findings')).__name__}); refusing to score it as a clean review.")
    comments = engine_report_to_review_comments(report)
    (repo_path / _REVIEW_OUTPUT_FILE).write_text(json.dumps(comments, indent=2), encoding="utf-8")
    return len(comments)


def _read_pr_review_metrics(output_dir: Path, execution_time: float) -> AgentMetrics:
    transcript = output_dir / "agent-transcript.log"
    if not transcript.exists():
        return AgentMetrics(execution_time=execution_time)
    metrics = parse_metrics(transcript.read_text(encoding="utf-8").splitlines(keepends=True))
    if metrics is None:
        return AgentMetrics(execution_time=execution_time)
    return metrics.model_copy(update={"execution_time": execution_time})


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
    """Run the engine's complete local review pipeline and write review.json.

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

    repo_path = repo_path.resolve()
    output_dir = output_dir.resolve()
    settings = _load_pr_review_settings()
    engine_root = _resolve_pr_review_root(settings)
    pwsh = _resolve_pwsh()
    severity = min_severity or settings["min_severity"]
    bcquality_cfg = settings["bcquality"]
    bcquality_repo = bcquality_repo or bcquality_cfg["repo"]
    bcquality_ref = bcquality_ref or bcquality_cfg["ref"]
    bcquality_local_path = bcquality_local_path or bcquality_cfg["local_path"]
    custom_bcquality = any((bcquality_repo, bcquality_ref, bcquality_local_path))
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

    engine = engine_root / "agents" / "ALReviewAgent" / "scripts" / "Invoke-CopilotPRReview.ps1"
    env = {
        **os.environ,
        "REVIEW_SOURCE": "local",
        "REVIEW_PHASE": "all",
        "BASE_REF": entry.base_commit,
        "REVIEW_TARGET_WORKSPACE": str(repo_path),
        "REVIEW_WORKSPACE": str(trusted_workspace),
        "REVIEW_OUTPUT_DIR": str(output_dir),
        "BCQUALITY_ROOT": str(bcquality_root),
        "COPILOT_MODEL": model,
        "AGENT_MINIMUM_SEVERITY": severity,
    }

    config = _build_experiment_configuration(engine_root, bcquality_root, bcquality_sha, custom_bcquality)

    start = time.monotonic()
    try:
        result = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(engine)],
            cwd=str(repo_path),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
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
        return _read_pr_review_metrics(output_dir, time.monotonic() - start), config
