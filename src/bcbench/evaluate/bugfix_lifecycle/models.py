from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bcbench.agent.shared.contained_process import AgentExecutionPolicy
from bcbench.agent.shared.env import production_agent_profile_environment
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput
from bcbench.types import AgentRuntimeConfig, ContainerConfig, EvaluationContext

if TYPE_CHECKING:
    from bcbench.dataset import BugFixEntry

_SETUP_OS_USERNAME = re.compile(r"bcb-[a-f0-9]{7}-[a-f0-9]{6}", re.IGNORECASE)
_SETUP_BC_USERNAME = re.compile(r"bca-[a-f0-9]{7}-[a-f0-9]{6}", re.IGNORECASE)
_PRODUCTION_AGENT_PROFILE_PATH_CHANNELS = ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP")


@dataclass(frozen=True)
class BugFixLifecyclePaths:
    entry_root: Path
    baseline_workspace: Path
    agent_workspace: Path
    agent_logs: Path
    agent_tools: Path
    mounted_staging: Path
    evaluator_workspaces: Path
    evidence: Path
    protected_root: Path
    trusted_source: Path
    checkpoints: Path
    final_results: Path


@dataclass(frozen=True)
class OwnedLifecycleRoot:
    path: Path
    ownership_token: str

    def __post_init__(self) -> None:
        if not self.ownership_token.strip():
            raise ValueError("ownership_token must be a non-empty string")

    @property
    def marker_path(self) -> Path:
        return self.path / ".bcbench-owned"


@dataclass(frozen=True)
class ProvisionedLifecycleResources:
    instance_id: str
    paths: BugFixLifecyclePaths
    container_name: str
    expected_container_id: str
    expected_container_invocation_id: str
    agent_os_username: str
    agent_bc_username: str
    agent_os_sid: str
    benchmark_root: Path
    staged_worker_path: Path
    base_python: Path
    python_base_prefix: Path
    cleanup_tool_roots: tuple[Path, ...] = ()
    acl_paths: tuple[Path, ...] = ()
    compiler_helper_roots: tuple[OwnedLifecycleRoot, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "instance_id",
            "container_name",
            "expected_container_id",
            "expected_container_invocation_id",
            "agent_os_username",
            "agent_bc_username",
            "agent_os_sid",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if _SETUP_OS_USERNAME.fullmatch(self.agent_os_username.strip()) is None:
            raise ValueError("Production agent_os_username must be a setup-owned OS username")
        if _SETUP_BC_USERNAME.fullmatch(self.agent_bc_username.strip()) is None:
            raise ValueError("Production agent_bc_username must be a setup-owned BC username")
        if re.fullmatch(r"S-\d(?:-\d+)+", self.agent_os_sid.strip(), re.IGNORECASE) is None:
            raise ValueError("Production agent_os_sid must be a Windows SID")
        object.__setattr__(self, "cleanup_tool_roots", tuple(self.cleanup_tool_roots))
        object.__setattr__(self, "acl_paths", tuple(self.acl_paths))
        object.__setattr__(self, "compiler_helper_roots", tuple(self.compiler_helper_roots))


@dataclass(frozen=True)
class BugFixLifecycleRequest:
    context: EvaluationContext[BugFixEntry]
    provisioned_resources: ProvisionedLifecycleResources
    evaluator_container: ContainerConfig
    agent_runtime: AgentRuntimeConfig
    agent_execution_policy: AgentExecutionPolicy
    replay_patch: Path | None = None
    replay_timeout: bool = False
    rehearsal_iterations: int = 0

    def __post_init__(self) -> None:
        if self.replay_timeout and self.replay_patch is None:
            raise ValueError("replay_timeout requires replay_patch")
        if type(self.rehearsal_iterations) is not int or not 0 <= self.rehearsal_iterations <= 100:
            raise ValueError("rehearsal_iterations must be an integer between 0 and 100")
        if self.context.entry.instance_id != self.provisioned_resources.instance_id:
            raise ValueError("Lifecycle entry must match provisioned resources")
        if self.evaluator_container.name != self.agent_runtime.container.name:
            raise ValueError("Evaluator and agent runtime containers must refer to the same container")
        if self.evaluator_container.name != self.provisioned_resources.container_name:
            raise ValueError("Evaluator container must match provisioned resources")
        if not self.agent_execution_policy.contain_process_tree:
            raise ValueError("Production agent execution must contain the process tree")
        restricted_identity = self.agent_execution_policy.restricted_identity
        if restricted_identity is None:
            raise ValueError("Production agent execution requires a restricted identity")
        if not self.agent_execution_policy.allowlist_environment:
            raise ValueError("Production agent execution must allowlist the environment")
        local_machine = os.environ.get("COMPUTERNAME", "").strip().casefold()
        local_domains = {".", *([local_machine] if local_machine else [])}
        if restricted_identity.domain.strip().casefold() not in local_domains:
            raise ValueError("Production restricted identity must use local Windows domain '.' or the local machine name")
        restricted_username = _normalized_windows_local_username(
            restricted_identity.username,
            "restricted identity username",
        )
        agent_os_username = _normalized_windows_local_username(
            self.agent_os_username,
            "agent_os_username",
        )
        if restricted_username != agent_os_username:
            raise ValueError("Production restricted identity username must match agent_os_username")
        agent_bc_username = _normalized_bc_username(self.agent_bc_username)
        runtime_bc_username = _normalized_bc_username(self.agent_runtime.container.username)
        if runtime_bc_username != agent_bc_username:
            raise ValueError("Production agent runtime BC username must match agent_bc_username")
        evaluator_bc_username = _normalized_bc_username(self.evaluator_container.username)
        if evaluator_bc_username == agent_bc_username:
            raise ValueError("Evaluator and agent BC usernames must differ")
        if self.evaluator_container.password == self.agent_runtime.container.password:
            raise ValueError("Evaluator and agent passwords must differ")
        environment_overrides = dict(self.agent_execution_policy.environment_overrides)
        expected_environment = production_agent_profile_environment(self.paths.agent_logs)
        if set(environment_overrides) != set(expected_environment):
            raise ValueError("Production policy must set all and only the agent profile environment overrides")
        from bcbench.evaluate.bugfix_lifecycle.path_safety import require_strict_descendant

        for name in _PRODUCTION_AGENT_PROFILE_PATH_CHANNELS:
            raw_path = Path(environment_overrides[name])
            canonical_path = require_strict_descendant(
                raw_path,
                self.paths.agent_logs,
                f"Production policy {name}",
                "agent_logs",
            )
            if raw_path != canonical_path:
                raise ValueError(f"Production policy {name} must be canonical: {canonical_path}")
            if not canonical_path.is_dir() or canonical_path.is_symlink():
                raise ValueError(f"Production policy {name} must be an existing directory: {canonical_path}")
        user_profile = environment_overrides["USERPROFILE"]
        if environment_overrides["HOMEDRIVE"] + environment_overrides["HOMEPATH"] != user_profile:
            raise ValueError("Production policy HOMEDRIVE and HOMEPATH must reconstruct USERPROFILE")
        if environment_overrides != expected_environment:
            raise ValueError("Production policy profile environment overrides must use the agent_logs/profile layout")
        from bcbench.evaluate.bugfix_lifecycle.path_safety import validate_provisioned_lifecycle_resources

        object.__setattr__(
            self,
            "provisioned_resources",
            validate_provisioned_lifecycle_resources(self.provisioned_resources),
        )

    @property
    def paths(self) -> BugFixLifecyclePaths:
        return self.provisioned_resources.paths

    @property
    def expected_container_id(self) -> str:
        return self.provisioned_resources.expected_container_id

    @property
    def expected_container_invocation_id(self) -> str:
        return self.provisioned_resources.expected_container_invocation_id

    @property
    def agent_os_username(self) -> str:
        return self.provisioned_resources.agent_os_username

    @property
    def agent_bc_username(self) -> str:
        return self.provisioned_resources.agent_bc_username

    @property
    def agent_os_sid(self) -> str:
        return self.provisioned_resources.agent_os_sid

    @property
    def python_base_prefix(self) -> Path:
        return self.provisioned_resources.python_base_prefix

    @property
    def acl_paths(self) -> tuple[Path, ...]:
        return self.provisioned_resources.acl_paths

    @property
    def compiler_helper_roots(self) -> tuple[OwnedLifecycleRoot, ...]:
        return self.provisioned_resources.compiler_helper_roots


@dataclass(frozen=True)
class SubmissionAnalysis:
    submission: GeneratedBugFixOutput
    fix_error: str | None = None
    test_error: str | None = None

    @property
    def fix_is_safe(self) -> bool:
        return self.fix_error is None

    @property
    def test_is_safe(self) -> bool:
        return self.test_error is None


@dataclass(frozen=True)
class TrustedSource:
    repository: Path
    commit: str


@dataclass(frozen=True)
class ContainerIdentity:
    container_id: str
    image_id: str
    hostname: str
    mounts: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "mounts", tuple(sorted(self.mounts)))

    def to_dict(self) -> dict[str, object]:
        return {
            "container_id": self.container_id,
            "image_id": self.image_id,
            "hostname": self.hostname,
            "mounts": list(self.mounts),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ContainerIdentity:
        return cls(
            container_id=_required_string(value, "container_id"),
            image_id=_required_string(value, "image_id"),
            hostname=_required_string(value, "hostname"),
            mounts=_required_string_tuple(value, "mounts"),
        )


@dataclass(frozen=True)
class AppInventoryEntry:
    app_id: str
    name: str
    publisher: str
    version: str
    package_id: str | None
    scope: str
    installed: bool
    synchronized: bool
    content_hash: str | None

    def __post_init__(self) -> None:
        if self.content_hash is not None:
            object.__setattr__(self, "content_hash", self.content_hash.lower())

    def to_dict(self) -> dict[str, object]:
        return {
            "app_id": self.app_id,
            "name": self.name,
            "publisher": self.publisher,
            "version": self.version,
            "package_id": self.package_id,
            "scope": self.scope,
            "installed": self.installed,
            "synchronized": self.synchronized,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> AppInventoryEntry:
        return cls(
            app_id=_required_string(value, "app_id"),
            name=_required_string(value, "name"),
            publisher=_required_string(value, "publisher"),
            version=_required_string(value, "version"),
            package_id=_optional_string(value, "package_id"),
            scope=_required_string(value, "scope"),
            installed=_required_bool(value, "installed"),
            synchronized=_required_bool(value, "synchronized"),
            content_hash=_optional_string(value, "content_hash"),
        )


@dataclass(frozen=True)
class CheckpointManifest:
    name: str
    backup_path: Path
    sha256: str
    database_name: str
    database_folder: str
    container: ContainerIdentity
    apps: tuple[AppInventoryEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "apps", tuple(sorted(self.apps, key=_app_sort_key)))
        object.__setattr__(self, "sha256", self.sha256.lower())

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "backup_path": str(self.backup_path),
            "sha256": self.sha256,
            "database_name": self.database_name,
            "database_folder": self.database_folder,
            "container": self.container.to_dict(),
            "apps": [app.to_dict() for app in self.apps],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CheckpointManifest:
        return cls(
            name=_required_string(value, "name"),
            backup_path=Path(_required_string(value, "backup_path")),
            sha256=_required_string(value, "sha256"),
            database_name=_required_string(value, "database_name"),
            database_folder=_required_string(value, "database_folder"),
            container=ContainerIdentity.from_dict(_required_mapping(value, "container")),
            apps=tuple(AppInventoryEntry.from_dict(app) for app in _required_mapping_tuple(value, "apps")),
        )


@dataclass(frozen=True)
class ProjectPublication:
    project_paths: tuple[str, ...]
    package_paths: tuple[Path, ...]
    apps: tuple[AppInventoryEntry, ...]
    evidence_paths: tuple[Path, ...]

    def __init__(
        self,
        project_paths: tuple[str, ...],
        package_paths: tuple[Path, ...],
        apps: tuple[AppInventoryEntry, ...] = (),
        evidence_paths: tuple[Path, ...] = (),
    ) -> None:
        object.__setattr__(self, "project_paths", tuple(project_paths))
        object.__setattr__(self, "package_paths", tuple(package_paths))
        object.__setattr__(self, "apps", tuple(apps))
        object.__setattr__(self, "evidence_paths", tuple(evidence_paths))


def _required_string(value: Mapping[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{name} must be a non-empty string")
    return item


def _required_string_tuple(value: Mapping[str, object], name: str) -> tuple[str, ...]:
    field = value.get(name)
    if not isinstance(field, list):
        raise TypeError(f"{name} must be a list of strings")
    strings: list[str] = []
    for item in field:
        if not isinstance(item, str):
            raise TypeError(f"{name} must be a list of strings")
        strings.append(item)
    return tuple(strings)


def _required_mapping(value: Mapping[str, object], name: str) -> Mapping[str, object]:
    return _string_keyed_mapping(value.get(name), f"{name} must be an object")


def _required_mapping_tuple(value: Mapping[str, object], name: str) -> tuple[Mapping[str, object], ...]:
    field = value.get(name)
    if not isinstance(field, list):
        raise TypeError(f"{name} must be a list of objects")
    return tuple(_string_keyed_mapping(item, f"{name} must contain objects") for item in field)


def _string_keyed_mapping(value: object, error: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(error)
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{error}; object keys must be strings")
        result[key] = item
    return result


def _required_bool(value: Mapping[str, object], name: str) -> bool:
    item = value.get(name)
    if not isinstance(item, bool):
        raise TypeError(f"{name} must be a boolean")
    return item


def _optional_string(value: Mapping[str, object], name: str) -> str | None:
    item = value.get(name)
    if item is None:
        return None
    if not isinstance(item, str) or not item:
        raise ValueError(f"{name} must be null or a non-empty string")
    return item


def _normalized_windows_local_username(username: str, field_name: str) -> str:
    normalized = username.strip()
    if "\\" in normalized or "@" in normalized:
        raise ValueError(f"{field_name} must be an unqualified local Windows username")
    return normalized.casefold()


def _normalized_bc_username(username: str) -> str:
    return username.strip().casefold()


def _app_sort_key(app: AppInventoryEntry) -> tuple[object, ...]:
    return (
        app.app_id,
        app.publisher,
        app.name,
        app.version,
        "" if app.package_id is None else app.package_id,
        app.scope,
        app.installed,
        app.synchronized,
        "" if app.content_hash is None else app.content_hash,
    )
