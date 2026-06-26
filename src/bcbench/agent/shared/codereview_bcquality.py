"""Live BCQuality consumption for the code-review category.

Faithfully replicates how microsoft/BCApps consumes microsoft/BCQuality today
(BCApps#8700): clone BCQuality at a pinned SHA, filter the clone to the allowed
layers/knowledge, make the filtered clone the agent working directory, and route
the agent through skills/entry.md with a task-context document.

This module only provides the building blocks (config parsing, clone, filter,
task-context, bootstrap prompt). Wiring into the copilot agent lives separately so
the bug-fix / test-generation categories are unaffected.

SECURITY: the clone becomes the agent CWD, so its skill/knowledge files are read
before the diff. `ref` MUST be a reviewed full commit SHA and `repo` MUST be an
http(s) URL pointing at a trusted source.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from jinja2 import Template

from bcbench.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "BCQualityConfig",
    "FilterReport",
    "RemovedEntry",
    "build_bootstrap_prompt",
    "build_task_context",
    "clone_bcquality",
    "filter_clone",
    "glob_match",
    "parse_bcquality_config",
    "prepare_bcquality_workspace",
    "write_task_context",
]

_LAYERS: tuple[str, ...] = ("microsoft", "community", "custom")
_KNOWN_LAYERS: frozenset[str] = frozenset(_LAYERS)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TASK_CONTEXT_DIMENSIONS: tuple[str, ...] = ("technologies", "countries", "application-area", "bc-version")
_TASK_CONTEXT_FILENAME = "_task-context.json"
_FILTER_REPORT_FILENAME = "_filter-report.json"


@dataclass(frozen=True)
class BCQualityConfig:
    enabled: bool
    repo: str
    ref: str
    enabled_layers: tuple[str, ...]
    disabled_skills: tuple[str, ...]
    knowledge_allow: tuple[str, ...]
    knowledge_deny: tuple[str, ...]
    task_context: dict[str, tuple[str, ...]]

    @classmethod
    def from_agent_config(cls, agent_config: dict) -> BCQualityConfig | None:
        raw = agent_config.get("bcquality")
        if not isinstance(raw, dict):
            return None

        knowledge = raw.get("knowledge") or {}
        task_context_raw = raw.get("task-context") or {}
        task_context = {dim: _as_str_tuple(task_context_raw.get(dim)) for dim in _TASK_CONTEXT_DIMENSIONS if dim in task_context_raw}

        config = cls(
            enabled=bool(raw.get("enabled", False)),
            repo=str(raw.get("repo", "")).strip(),
            ref=str(raw.get("ref", "")).strip(),
            enabled_layers=_as_str_tuple(raw.get("enabled-layers")) or ("microsoft",),
            disabled_skills=_as_str_tuple(raw.get("disabled-skills")),
            knowledge_allow=_as_str_tuple(knowledge.get("allow")),
            knowledge_deny=_as_str_tuple(knowledge.get("deny")),
            task_context=task_context,
        )
        config.validate()
        return config

    def validate(self) -> None:
        unknown = [layer for layer in self.enabled_layers if layer not in _KNOWN_LAYERS]
        if unknown:
            raise ValueError(f"Unknown bcquality enabled-layers value(s): {unknown}. Allowed: {sorted(_KNOWN_LAYERS)}.")
        if not self.enabled:
            return
        if not _SHA_RE.match(self.ref):
            raise ValueError(f"bcquality.ref must be a full 40-character commit SHA when enabled (got {self.ref!r}). Pin to a reviewed SHA for security.")
        if not re.match(r"^https?://", self.repo):
            raise ValueError(f"bcquality.repo must be an http(s) URL (got {self.repo!r}).")


@dataclass(frozen=True)
class RemovedEntry:
    path: str
    kind: str  # "knowledge" | "skill"
    reason: str


@dataclass
class FilterReport:
    bcquality_root: str
    enabled_layers: list[str]
    disabled_skills: list[str]
    knowledge_allow: list[str]
    knowledge_deny: list[str]
    removed: list[RemovedEntry] = field(default_factory=list)

    @property
    def removed_count(self) -> int:
        return len(self.removed)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["removed_count"] = self.removed_count
        return data


def parse_bcquality_config(agent_config: dict) -> BCQualityConfig | None:
    return BCQualityConfig.from_agent_config(agent_config)


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),)


def _glob_to_regex(pattern: str) -> str:
    p = pattern.replace("\\", "/").strip()
    parts: list[str] = ["^"]
    i = 0
    while i < len(p):
        c = p[i]
        if c == "*":
            if i + 1 < len(p) and p[i + 1] == "*":
                parts.append(".*")
                i += 2
                if i < len(p) and p[i] == "/":
                    i += 1
                continue
            parts.append("[^/]*")
        elif c == "?":
            parts.append("[^/]")
        else:
            parts.append(re.escape(c))
        i += 1
    parts.append("$")
    return "".join(parts)


def glob_match(path: str, pattern: str) -> bool:
    normalized = pattern.replace("\\", "/").strip()
    if not normalized:
        return False
    return re.match(_glob_to_regex(normalized), path) is not None


def _run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}")


def clone_bcquality(config: BCQualityConfig, dest: Path) -> Path:
    """Shallow-clone BCQuality at the pinned SHA into dest (overwriting if present)."""
    config.validate()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    logger.info(f"Cloning BCQuality {config.repo}@{config.ref} into {dest}")
    _run_git(["init", "--quiet"], cwd=dest)
    _run_git(["remote", "add", "origin", config.repo], cwd=dest)
    _run_git(["fetch", "--quiet", "--depth", "1", "origin", config.ref], cwd=dest)
    _run_git(["checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=dest)
    return dest


def _is_within(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def filter_clone(root: Path, config: BCQualityConfig, report_path: Path | None = None) -> FilterReport:
    """Prune a BCQuality clone per enabled-layers + knowledge allow/deny globs.

    Mirrors BCApps tools/BCQuality/scripts/Invoke-BCQualityFilter.ps1. Meta-skills
    under the top-level /skills/ are never removed.
    """
    if not root.is_dir():
        raise FileNotFoundError(f"BCQuality root not found: {root}")
    report_path = report_path or (root / _FILTER_REPORT_FILENAME)
    root_resolved = root.resolve()
    removed: list[RemovedEntry] = []

    for layer in _LAYERS:
        kb_root = root / layer / "knowledge"
        if not kb_root.is_dir():
            continue
        for md in sorted(kb_root.rglob("*.md")):
            rel = md.relative_to(root).as_posix()
            reason: str | None = None
            if layer not in config.enabled_layers:
                reason = "layer-disabled"
            elif config.knowledge_allow and not any(glob_match(rel, pat) for pat in config.knowledge_allow):
                reason = "allow-list-miss"
            if reason is None and config.knowledge_deny and any(glob_match(rel, pat) for pat in config.knowledge_deny):
                reason = "deny-list-hit"
            if reason:
                md.unlink()
                removed.append(RemovedEntry(path=rel, kind="knowledge", reason=reason))

    for layer in _LAYERS:
        skills_root = root / layer / "skills"
        if not skills_root.is_dir():
            continue
        if layer not in config.enabled_layers:
            for md in sorted(skills_root.rglob("*.md")):
                rel = md.relative_to(root).as_posix()
                md.unlink()
                removed.append(RemovedEntry(path=rel, kind="skill", reason="layer-disabled"))
            continue
        for disabled in config.disabled_skills:
            normalized = disabled.replace("\\", "/").strip()
            if not normalized or not normalized.startswith(f"{layer}/"):
                continue
            target = (root / normalized).resolve()
            if not _is_within(target, root_resolved):
                logger.warning(f"Skipping unsafe disabled-skill path '{normalized}' (escapes BCQuality root).")
                continue
            if target.is_file():
                target.unlink()
                removed.append(RemovedEntry(path=normalized, kind="skill", reason="configuration"))

    report = FilterReport(
        bcquality_root=str(root),
        enabled_layers=list(config.enabled_layers),
        disabled_skills=list(config.disabled_skills),
        knowledge_allow=list(config.knowledge_allow),
        knowledge_deny=list(config.knowledge_deny),
        removed=removed,
    )
    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    logger.info(f"BCQuality filter: removed {report.removed_count} file(s). Report: {report_path}")
    return report


def build_task_context(config: BCQualityConfig) -> dict:
    context: dict[str, object] = {
        "goal": "review pull request",
        "inputs-available": ["pr-diff", "file-path", "repository"],
        "enabled-layers": list(config.enabled_layers),
        "disabled-skills": list(config.disabled_skills),
    }
    for dim in _TASK_CONTEXT_DIMENSIONS:
        if dim in config.task_context:
            context[dim] = list(config.task_context[dim])
    return context


def write_task_context(root: Path, context: dict) -> Path:
    path = root / _TASK_CONTEXT_FILENAME
    path.write_text(json.dumps(context, indent=2), encoding="utf-8")
    logger.info(f"Task context written to {path}")
    return path


def build_bootstrap_prompt(template: str, repo_path: Path, task_context_filename: str, review_output_file: str) -> str:
    return Template(template).render(
        repo=repo_path.as_posix(),
        task_context_filename=task_context_filename,
        review_output_file=review_output_file,
    )


def prepare_bcquality_workspace(config: BCQualityConfig, clone_dest: Path, repo_path: Path, review_output_file: str, bootstrap_template: str) -> tuple[Path, str]:
    """Clone + filter BCQuality, write task-context, and render the bootstrap prompt.

    Returns:
        Tuple of (filtered BCQuality clone root, bootstrap prompt string).
    """
    clone_bcquality(config, clone_dest)
    entry_skill = clone_dest / "skills" / "entry.md"
    if not entry_skill.exists():
        raise FileNotFoundError(f"BCQuality clone at {clone_dest} is missing skills/entry.md; check bcquality repo and ref.")
    filter_clone(clone_dest, config)
    context = build_task_context(config)
    context_path = write_task_context(clone_dest, context)
    prompt = build_bootstrap_prompt(bootstrap_template, repo_path, context_path.name, review_output_file)
    return clone_dest, prompt
