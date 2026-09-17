from collections.abc import Mapping
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
    def from_dict(cls, value: Mapping[str, object]) -> "ContainerIdentity":
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
    def from_dict(cls, value: Mapping[str, object]) -> "AppInventoryEntry":
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
    def from_dict(cls, value: Mapping[str, object]) -> "CheckpointManifest":
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
