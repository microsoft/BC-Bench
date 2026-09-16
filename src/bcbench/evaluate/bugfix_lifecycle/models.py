from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BugFixLifecyclePaths:
    entry_root: Path
    baseline_workspace: Path
    agent_workspace: Path
    agent_logs: Path
    mounted_staging: Path
    evaluator_workspaces: Path
    evidence: Path
    protected_root: Path
    trusted_source: Path
    checkpoints: Path
    final_results: Path


@dataclass(frozen=True)
class TrustedSource:
    repository: Path
    commit: str
