from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(map(_freeze, value))
    return value


def mutable_config(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: mutable_config(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return list(map(mutable_config, value))
    return value


@dataclass(frozen=True, kw_only=True)
class AgentSettings:
    timeout: int
    shared_config: Mapping[str, Any]
    environment: Mapping[str, str]
    instructions_root: Path
    instruction_source_naming: str
    plugin_root: Path
    plugin_manifest: Path
    problem_statement_dest_dir: str
    copilot_executable: str | None = None
    claude_executable: str | None = None
    pwsh_executable: str | None = None
    gh_executable: str | None = None
    git_executable: str | None = None
    compiler_root: Path = Path(r"C:\ProgramData\BcContainerHelper\compiler")
    artifact_cache_root: Path = Path(r"C:\bcartifacts.cache")
    dotnet_shared: Path = Path(r"C:\Program Files\dotnet\shared")

    def __post_init__(self) -> None:
        object.__setattr__(self, "shared_config", _freeze(self.shared_config))
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))


@dataclass(frozen=True, kw_only=True)
class PRReviewSettings:
    engine_path: Path | None
    min_severity: str
    prepare_script: Path
    findings_filename: str = "al-code-review-findings.json"
    review_filename: str = "review.json"
    metrics_filename: str = "_run-metrics.json"
