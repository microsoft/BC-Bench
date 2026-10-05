"""Business Central artifacts downloaded by BcContainerHelper: version folders and symbol (*.app) files."""

import logging
import shutil
from pathlib import Path
from typing import Final, Literal

logger = logging.getLogger(__name__)

# BcContainerHelper's default artifact cache (its `bcartifactsCacheFolder` setting)
DEFAULT_ARTIFACTS_CACHE: Final = Path(r"C:\bcartifacts.cache")
# AL's default package cache folder for symbol (*.app) files inside a project
ALPACKAGES_DIRNAME: Final = ".alpackages"

type ArtifactType = Literal["sandbox", "onprem"]


def resolve_artifact_version_root(version: str, artifacts_cache: Path = DEFAULT_ARTIFACTS_CACHE, artifact_type: ArtifactType = "sandbox") -> Path | None:
    """Return the newest BcContainerHelper artifact folder matching a major.minor version.

    BcContainerHelper expands a major.minor version (e.g. "27.2") to a full ``<major>.<minor>.<build>.<revision>``
    folder under ``<artifacts_cache>/<artifact_type>/``. We glob, lexically sort, and pick the newest -- BC's
    full-version fields are constant-width in practice, so a lexical sort matches a numeric one.

    Returns None when no matching artifact has been downloaded yet.
    """
    version_roots = sorted((artifacts_cache / artifact_type).glob(f"{version}.*"))
    return version_roots[-1] if version_roots else None


def copy_symbol_apps(project_dir: Path, version: str, artifacts_cache: Path = DEFAULT_ARTIFACTS_CACHE, artifact_type: ArtifactType = "sandbox", symbols_dirname: str = ALPACKAGES_DIRNAME) -> None:
    """Copy all *.app symbol files from the BC artifact cache into the project's symbol folder."""
    version_root = resolve_artifact_version_root(version, artifacts_cache, artifact_type)
    if version_root is None:
        raise FileNotFoundError(f"No BC artifact for version {version} under {artifacts_cache / artifact_type}. Download it with BcContainerHelper first.")

    app_files = list(version_root.rglob("*.app"))
    if not app_files:
        raise FileNotFoundError(f"No *.app files found under {version_root}.")

    symbols_dir = project_dir / symbols_dirname
    symbols_dir.mkdir(parents=True, exist_ok=True)
    for app_file in app_files:
        shutil.copy2(app_file, symbols_dir / app_file.name)
    logger.info(f"Copied {len(app_files)} *.app files from {version_root} to {symbols_dir}")
