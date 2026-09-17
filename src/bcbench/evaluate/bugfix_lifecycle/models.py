from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bcbench.agent.shared.contained_process import AgentExecutionPolicy
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput
from bcbench.types import AgentRuntimeConfig, ContainerConfig, EvaluationContext

if TYPE_CHECKING:
    from bcbench.dataset import BugFixEntry

_SETUP_OS_USERNAME = re.compile(r"bcb-[a-f0-9]{7}-[a-f0-9]{6}", re.IGNORECASE)
_SETUP_BC_USERNAME = re.compile(r"bca-[a-f0-9]{7}-[a-f0-9]{6}", re.IGNORECASE)
_PRODUCTION_AGENT_ENVIRONMENT_CHANNELS = frozenset({"TEMP", "TMP"})


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
class BugFixLifecycleRequest:
    context: EvaluationContext[BugFixEntry]
    paths: BugFixLifecyclePaths
    evaluator_container: ContainerConfig
    agent_runtime: AgentRuntimeConfig
    agent_execution_policy: AgentExecutionPolicy
    expected_container_id: str
    expected_container_invocation_id: str
    agent_os_username: str
    agent_bc_username: str
    agent_os_sid: str
    acl_paths: tuple[Path, ...] = ()
    compiler_helper_roots: tuple[OwnedLifecycleRoot, ...] = ()
    replay_patch: Path | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "expected_container_id",
            "expected_container_invocation_id",
            "agent_os_username",
            "agent_bc_username",
            "agent_os_sid",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.evaluator_container.name != self.agent_runtime.container.name:
            raise ValueError("Evaluator and agent runtime containers must refer to the same container")
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
        if _SETUP_OS_USERNAME.fullmatch(self.agent_os_username.strip()) is None:
            raise ValueError("Production agent_os_username must be a setup-owned OS username")
        if _SETUP_BC_USERNAME.fullmatch(self.agent_bc_username.strip()) is None:
            raise ValueError("Production agent_bc_username must be a setup-owned BC username")
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
        if environment_overrides:
            unexpected_channels = set(environment_overrides) - _PRODUCTION_AGENT_ENVIRONMENT_CHANNELS
            if unexpected_channels:
                raise ValueError("Production policy environment overrides may only set explicit agent runtime channels")
            expected_temp = str(self.paths.agent_logs / "temp")
            if environment_overrides != {"TEMP": expected_temp, "TMP": expected_temp}:
                raise ValueError("Production policy TEMP and TMP must both use agent_logs/temp")
        object.__setattr__(self, "acl_paths", tuple(self.acl_paths))
        object.__setattr__(self, "compiler_helper_roots", tuple(self.compiler_helper_roots))
        from bcbench.evaluate.bugfix_lifecycle.path_safety import validate_owned_lifecycle_roots

        object.__setattr__(
            self,
            "compiler_helper_roots",
            validate_owned_lifecycle_roots(
                self.compiler_helper_roots,
                self.paths,
                self.expected_container_invocation_id,
            ),
        )


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
        mounts = value.get("mounts")
        if not isinstance(mounts, list) or not all(isinstance(mount, str) for mount in mounts):
            raise ValueError("Container identity mounts must be a list of strings")
        return cls(
            container_id=_required_string(value, "container_id"),
            image_id=_required_string(value, "image_id"),
            hostname=_required_string(value, "hostname"),
            mounts=tuple(mounts),
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
        container = value.get("container")
        apps = value.get("apps")
        if not isinstance(container, Mapping):
            raise TypeError("Checkpoint container identity must be an object")
        if not isinstance(apps, list) or not all(isinstance(app, Mapping) for app in apps):
            raise ValueError("Checkpoint application inventory must be a list of objects")
        return cls(
            name=_required_string(value, "name"),
            backup_path=Path(_required_string(value, "backup_path")),
            sha256=_required_string(value, "sha256"),
            database_name=_required_string(value, "database_name"),
            database_folder=_required_string(value, "database_folder"),
            container=ContainerIdentity.from_dict(container),
            apps=tuple(AppInventoryEntry.from_dict(app) for app in apps),
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
