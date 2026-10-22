import hashlib
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, StrictBool, TypeAdapter

from bcbench.agent.copilot.cli import _find_copilot, invoke_copilot
from bcbench.agent.shared import build_prompt
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry, CodeReviewEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.types import AgentConfig, AgentMetrics, EvaluationCategory, ExperimentConfiguration

_ENV_KEYS = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "COPILOT_GITHUB_TOKEN",
        "GH_TOKEN",
        "GITHUB_TOKEN",
    }
)
_CLI_FLAGS = ("--no-auto-update", "--no-custom-instructions", "--disable-builtin-mcps", "--log-level=none", "--no-remote", "--no-remote-export")


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, check=True).stdout


def _configuration_manifest(root: Path) -> dict[str, str]:
    files = sorted(root.rglob("*"))
    if root.is_symlink() or any(path.is_symlink() or path.is_junction() for path in [root, *files]):
        raise AgentError("Agent configuration isolation does not accept links or junctions")
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()}


@contextmanager
def _quarantine_project_agents(repo: Path, evidence: dict[str, object], env: dict[str, str] | None = None) -> Iterator[None]:
    source = repo / ".github" / "agents"
    if not source.exists():
        yield
        return
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
        or not workspace
        or repo.resolve() != (Path(workspace).resolve() / "testbed")
        or not (repo / ".git").is_dir()
        or (repo / ".github").is_symlink()
        or (repo / ".github").is_junction()
    ):
        raise AgentError("Agent configuration quarantine is restricted to the hosted job's disposable testbed clone")
    if _git(repo, "status", "--porcelain", "--untracked-files=all", "--", ".github/agents"):
        raise AgentError("Agent configuration is modified or untracked; refusing to hide reviewed changes")
    entries = _git(repo, "ls-files", "-v", "-z", "--", ".github/agents").decode().split("\0")
    if any(not item.startswith("H ") for item in entries if item):
        raise AgentError("Agent configuration has unexpected index flags")
    paths = [item[2:] for item in entries if item]
    if not paths:
        raise AgentError("Agent configuration must be tracked before isolation")
    manifest = _configuration_manifest(source)
    before = _git(repo, "diff", "HEAD", "--no-ext-diff", "--binary", env=env)
    staged = _git(repo, "diff", "--cached", "HEAD", "--no-ext-diff", "--binary", env=env)
    changed = _git(repo, "diff", "--name-only", "-z", "HEAD").decode().split("\0")
    source_hashes = {path: hashlib.sha256((repo / path).read_bytes()).hexdigest() for path in changed if path and (repo / path).is_file()}
    record: dict[str, object] = {
        "path": ".github/agents",
        "files_sha256": manifest,
        "source_files_sha256": source_hashes,
        "diff_before_sha256": hashlib.sha256(before).hexdigest(),
        "restored": False,
    }
    evidence["quarantined_project_agents"] = record
    quarantine = Path(tempfile.mkdtemp(prefix="bcbench-agent-config-", dir=repo.parent))
    backup = quarantine / "agents"
    try:
        # Keep ordinary git diff HEAD (including model tool calls) byte-identical.
        _git(repo, "update-index", "--skip-worktree", "--", *paths)
        source.rename(backup)
        during = _git(repo, "diff", "HEAD", "--no-ext-diff", "--binary", env=env)
        if during != before or _git(repo, "diff", "--cached", "HEAD", "--no-ext-diff", "--binary", env=env) != staged:
            raise AgentError("Configuration isolation changed the reviewer-visible diff")
        record["diff_isolated_sha256"] = hashlib.sha256(during).hexdigest()
        yield
    finally:
        if backup.exists():
            if source.exists():
                raise AgentError("Agent configuration reappeared; original backup retained outside checkout")
            backup.rename(source)
        _git(repo, "update-index", "--no-skip-worktree", "--", *paths)
        quarantine.rmdir()
        if _configuration_manifest(source) != manifest:
            raise AgentError("Restored agent configuration differs from its original bytes")
        record["restored"] = True
        after = _git(repo, "diff", "HEAD", "--no-ext-diff", "--binary", env=env)
        record["diff_after_sha256"] = hashlib.sha256(after).hexdigest()
        if (
            after != before
            or _git(repo, "diff", "--cached", "HEAD", "--no-ext-diff", "--binary", env=env) != staged
            or any(not (repo / path).is_file() or hashlib.sha256((repo / path).read_bytes()).hexdigest() != digest for path, digest in source_hashes.items())
        ):
            raise AgentError("Review changed the intended source or diff; refusing to score contaminated output")


def isolated_environment(home: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key.upper() in _ENV_KEYS}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        COPILOT_HOME=str(home / ".copilot"),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_CACHE_HOME=str(home / ".cache"),
        APPDATA=str(home / "AppData" / "Roaming"),
        LOCALAPPDATA=str(home / "AppData" / "Local"),
        CI="true",
        COPILOT_AUTO_UPDATE="false",
    )
    return env


def _cli(cli: str, repo: Path, env: dict[str, str], *args: str) -> str:
    result = subprocess.run([cli, *_CLI_FLAGS, *args], cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    if result.returncode:
        raise AgentError(f"Isolated CLI preflight command {args[0]} failed with exit {result.returncode}; output withheld")
    return result.stdout


def _inventory(cli: str, repo: Path, env: dict[str, str], kind: str) -> list[dict[str, object]]:
    return TypeAdapter(list[dict[str, object]]).validate_json(_cli(cli, repo, env, kind, "list", "--json"), strict=True)


class SkillSource(BaseModel):
    name: str
    source: str
    enabled: StrictBool


def _disable_skills(cli: str, repo: Path, env: dict[str, str]) -> None:
    banner = _cli(cli, repo, env, "--version")
    if "GitHub Copilot CLI 1.0.88." not in banner.splitlines():
        raise AgentError("Isolated review requires native CLI 1.0.88")
    for value in _inventory(cli, repo, env, "skill"):
        item = SkillSource.model_validate(value)
        _cli(cli, repo, env, "skill", "disable", item.name)


def _sources(cli: str, repo: Path, env: dict[str, str]) -> dict[str, object]:
    skills = [SkillSource.model_validate(value) for value in _inventory(cli, repo, env, "skill")]
    plugins = _inventory(cli, repo, env, "plugin")
    if plugins:
        raise AgentError("Isolated review discovered plugins; refusing to run")
    if any(item.enabled for item in skills):
        raise AgentError("Isolated review discovered an enabled or unknown-state skill")
    return {
        "skills": [item.model_dump() for item in skills],
        "plugins": [],
        "custom_instructions_disabled": True,
        "discovered_instruction_count": len(_inventory(cli, repo, env, "instruction")),
    }


def _check_project_configuration(repo: Path) -> list[str]:
    # Fail closed rather than deleting source/configuration from the reviewed checkout.
    forbidden = (
        ".github/extensions",
        ".github/agents",
        ".claude/agents",
        ".agents/agents",
        ".github/hooks",
        ".github/copilot",
        ".copilot",
        ".mcp.json",
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".github/copilot-settings.json",
    )
    found = [relative for relative in forbidden if (repo / relative).exists()]
    if found:
        raise AgentError(f"Isolated review requires configuration adjudication before execution: {', '.join(found)}")
    return list(forbidden)


def run_isolated_review(
    entry: BaseDatasetEntry,
    model: str,
    repo_path: Path,
    output_dir: Path,
    config: AgentConfig,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    if not isinstance(entry, CodeReviewEntry):
        raise AgentError("Isolated review requires a code-review dataset entry")
    if config.instructions.enabled or config.skills.enabled or config.agents.enabled or any(plugin.get("enabled") for plugin in config.plugins):
        raise AgentError("Isolated review requires all configured instructions, skills, agents and plugins disabled")
    cli = _find_copilot()
    if cli is None:
        raise AgentError("Pinned Copilot CLI is unavailable")
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir / "_plain-review-evidence.json"
    experiment = ExperimentConfiguration(review_integration="none")
    evidence: dict[str, object] = {
        "schema_version": 1,
        "entry_id": entry.instance_id,
        "integration": "none",
        "status": "preflight",
        "model": model,
        "cli_version": "1.0.88",
        "minimum_severity": "Medium",
        "source_patch_sha256": hashlib.sha256(entry.patch.encode()).hexdigest(),
        "topology": "single generic review invocation; no BCQuality leaves",
        "started_at": datetime.now(UTC).isoformat(),
        "flags": list(_CLI_FLAGS),
        "evidence_limit": "CLI discovery inventories and isolated configuration before/after invocation, not proof of every file the model read. No raw prompt, environment, transcript or failure text retained.",
    }
    start = time.monotonic()
    stage = "preflight"
    try:
        with ExitStack() as stack:
            temp = stack.enter_context(tempfile.TemporaryDirectory(prefix="bcbench-plain-"))
            home = Path(temp)
            env = isolated_environment(home)
            stack.enter_context(_quarantine_project_agents(repo_path, evidence, env))
            evidence["absent_project_configuration"] = _check_project_configuration(repo_path)
            config_dir = home / ".copilot"
            config_dir.mkdir()
            configuration = {"disableAllHooks": True, "ide": {"autoConnect": False}, "memory": False, "autoUpdate": False, "customAgents": {"defaultLocalOnly": True}}
            (config_dir / "config.json").write_text(json.dumps(configuration), encoding="utf-8")
            evidence["isolated_configuration"] = configuration
            _disable_skills(cli, repo_path, env)
            evidence["before"] = _sources(cli, repo_path, env)
            prompt = build_prompt(entry, repo_path, config, EvaluationCategory.CODE_REVIEW, al_mcp=False)
            prompt += (
                "\nReport only Medium, High or Critical issues; omit Low/info findings. "
                "This is a plain review without BCQuality. Do not load skills, plugins, repository instructions, "
                "external review knowledge, or delegate review to subagents. Review the supplied source diff directly."
            )
            evidence["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
            stage = "review"
            evidence["status"] = "running"
            evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            metrics, _ = invoke_copilot(
                prompt=prompt,
                model=model,
                work_dir=repo_path,
                timeout=get_config().timeout.agent_execution,
                allow_all_tools=True,
                custom_instructions=False,
                env=env,
                extra_args=(*_CLI_FLAGS, "--excluded-tools=skill,task", "--no-bash-env"),
                log_transcript=False,
            )
            stage = "postflight"
            evidence["after"] = _sources(cli, repo_path, env)
            evidence["status"] = "completed"
            evidence["metrics"] = metrics.model_dump(mode="json") if metrics else None
            return metrics, experiment
    except subprocess.TimeoutExpired:
        evidence["status"] = "timeout"
        raise AgentTimeoutError("Isolated review timed out", metrics=AgentMetrics(execution_time=time.monotonic() - start), config=experiment) from None
    except (AgentError, OSError, ValueError, subprocess.SubprocessError) as exc:
        evidence["status"] = "failed"
        evidence["error_type"] = type(exc).__name__
        raise AgentError(f"Isolated review failed during {stage}: {type(exc).__name__}; raw output withheld") from None
    finally:
        evidence["stage"] = stage
        evidence["completed_at"] = datetime.now(UTC).isoformat()
        evidence["duration_seconds"] = time.monotonic() - start
        evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
