"""Setup operations for repository preparation."""

import json
from pathlib import Path
from uuid import uuid4

from bcbench.dataset.dataset_entry import RepoGroundedEntry
from bcbench.logger import get_logger
from bcbench.operations.git_operations import checkout_commit, clean_repo

logger = get_logger(__name__)

__all__ = ["bootstrap_app_json", "set_runtime_version", "setup_repo_prebuild"]

# Offset from BC platform major version to AL runtime version.
# E.g. platform 25.0 (BC 2024w2) → runtime 14.0, platform 27.0 → runtime 16.0
# See: BC-DeveloperExperience RuntimeVersion.cs
_PLATFORM_TO_RUNTIME_OFFSET = 11


def setup_repo_prebuild(entry: RepoGroundedEntry, repo_path: Path) -> None:
    """Setup repository before building - clean and checkout base commit.

    This is the first phase of repo setup that should be called BEFORE build_and_publish_projects.
    It prepares a clean slate at the base commit without any patches or problem statements.

    Args:
        entry: Dataset entry with instance metadata
        repo_path: Path to the repository
    """
    clean_repo(repo_path)
    checkout_commit(repo_path, entry.base_commit)


def bootstrap_app_json(
    app_folder: Path,
    name: str,
    bc_version: str,
    *,
    id_range: tuple[int, int] = (50100, 50149),
    publisher: str = "BC-Bench",
    app_version: str = "1.0.0.0",
    target: str = "OnPrem",
    app_id: str | None = None,
) -> Path:
    """Write a minimal, compilable ``app.json`` into ``app_folder``.

    Every AL app needs an ``app.json``; this bootstraps one for throwaway apps built by the
    harness (e.g. wrapping a generated query or test codeunit) so categories don't hand-roll manifests.

    Args:
        app_folder: Folder to create (if missing) and write ``app.json`` into.
        name: App name, also used as the publisher-facing app name.
        bc_version: BC platform version, e.g. ``"26.0.12345.0"`` or ``"26.0"``; its major version
            drives ``platform``, ``application`` and the derived ``runtime``.
        id_range: Inclusive object ID range for the app.
        publisher: App publisher.
        app_version: App version.
        target: App target, e.g. ``"OnPrem"`` or ``"Cloud"``.
        app_id: App GUID; a random one is generated when omitted.

    Returns:
        Path to the written ``app.json``.
    """
    major = _major_version(bc_version)
    if major is None:
        raise ValueError(f"Cannot derive major version from BC version: {bc_version!r}")

    id_from, id_to = id_range
    if id_from > id_to:
        raise ValueError(f"Invalid id_range: {id_range!r}")

    manifest: dict[str, object] = {
        "id": app_id or str(uuid4()),
        "name": name,
        "publisher": publisher,
        "version": app_version,
        "platform": f"{major}.0.0.0",
        "application": f"{major}.0.0.0",
        "idRanges": [{"from": id_from, "to": id_to}],
        "target": target,
    }

    runtime_major = major - _PLATFORM_TO_RUNTIME_OFFSET
    if runtime_major >= 1:
        manifest["runtime"] = f"{runtime_major}.0"

    app_folder.mkdir(parents=True, exist_ok=True)
    app_json_path = app_folder / "app.json"
    app_json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Bootstrapped {app_json_path} (name={name}, platform {major}.0.0.0, ids {id_from}-{id_to})")
    return app_json_path


def _major_version(version: str) -> int | None:
    try:
        return int(version.split(".")[0])
    except (ValueError, IndexError, AttributeError):
        return None


def set_runtime_version(repo_path: Path, project_paths: list[str]) -> None:
    """Set the AL runtime version in each project's app.json based on platform version.

    The AL compiler (altool) defaults to the latest runtime, enabling newer validation rules that reject older code.
    Setting the runtime to match the platform version makes the compiler behave like the version that originally compiled the code.

    Can be skipped when altool is not used.
    """
    for project_path in project_paths:
        app_json_path = repo_path / project_path / "app.json"
        if not app_json_path.is_file():
            continue

        try:
            app_json = json.loads(app_json_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            continue

        if app_json.get("runtime"):
            continue

        platform: str = app_json.get("platform", "")
        platform_major = _major_version(platform)
        if platform_major is None:
            continue

        runtime_major: int = platform_major - _PLATFORM_TO_RUNTIME_OFFSET
        if runtime_major < 1:
            continue

        runtime: str = f"{runtime_major}.0"
        app_json["runtime"] = runtime
        app_json_path.write_text(json.dumps(app_json, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Set runtime={runtime} in {app_json_path} (platform {platform})")
