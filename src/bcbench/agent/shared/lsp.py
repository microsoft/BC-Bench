import json
from pathlib import Path

from bcbench.agent.shared.altool_paths import (
    build_assembly_probing_paths,
    compiler_symbol_folder_for_container,
    resolve_artifact_lsp_paths,
    set_runtime_version,
)
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)

_AL_LSP_RELATIVE_PATH = Path(".github") / "lsp.json"


def _resolve_symbol_paths(entry: BaseDatasetEntry, category: EvaluationCategory, container_name: str) -> tuple[list[str], list[str]]:
    """Resolve (package_cache_paths, assembly_probing_paths) for the LSP server.

    Prefers the container's compiler folder when available — its single flat layout is the exact same arg shape AL-MCP uses.
    Falls back to the raw BC artifact cache for container-free local runs. Raises a clear error pointing at the symbol-download script when neither is present.
    """
    if container_name:
        compiler_folder, symbols_folder = compiler_symbol_folder_for_container(container_name)
        if symbols_folder.is_dir():
            logger.info(f"Using container compiler-folder symbols: {symbols_folder}")
            return [str(symbols_folder)], build_assembly_probing_paths(compiler_folder)

    artifact_paths = resolve_artifact_lsp_paths(entry.environment_setup_version)
    if artifact_paths is not None:
        package_cache_paths, assembly_probing_paths = artifact_paths
        logger.info(f"Using BC artifact cache symbols for v{entry.environment_setup_version}: {package_cache_paths}")
        return package_cache_paths, assembly_probing_paths

    raise AgentError(
        f"No AL symbols found for BC v{entry.environment_setup_version}. Run `./scripts/Download-BCSymbols.ps1 -Category {category.value} -InstanceId {entry.instance_id}` (no container required) and retry."
    )


def _build_lsp_args(project_paths: list[str], package_cache_paths: list[str], assembly_probing_paths: list[str]) -> list[str]:
    # `launchlspserver [<projects>...] [options]` — projects come first as positional args.
    args: list[str] = ["launchlspserver", *project_paths, "--packagecachepath", *package_cache_paths]
    if assembly_probing_paths:
        args.extend(["--assemblyprobingpaths", *assembly_probing_paths])
    return args


def build_lsp_config(entry: BaseDatasetEntry, category: EvaluationCategory, repo_path: Path, al_lsp: bool, container_name: str = "") -> bool:
    """Write Copilot's project-level LSP config to <repo_path>/.github/lsp.json.

    When ``al_lsp=False``, removes any stale config left over from a previous run and returns False.
    When True, writes the `lspServers.altool` entry pointing at `altool launchlspserver` and returns True.
    """
    lsp_config_path = repo_path / _AL_LSP_RELATIVE_PATH

    if not al_lsp:
        if lsp_config_path.is_file():
            lsp_config_path.unlink()
            logger.info(f"Removed stale LSP config: {lsp_config_path}")
        return False

    project_paths = [str(repo_path / p) for p in entry.project_paths]
    set_runtime_version(project_paths)

    package_cache_paths, assembly_probing_paths = _resolve_symbol_paths(entry, category, container_name)

    args = _build_lsp_args(
        project_paths=project_paths,
        package_cache_paths=package_cache_paths,
        assembly_probing_paths=assembly_probing_paths,
    )

    # Copilot CLI resolves `command` via PATH (absolute paths are silently rejected with
    # "Server <name> is configured but not available"). `al` is the published altool
    # wrapper installed via the .NET tool — it must be on PATH.
    lsp_config = {
        "lspServers": {
            "altool": {
                "command": "al",
                "args": args,
                "fileExtensions": {".al": "al"},
            }
        }
    }

    lsp_config_path.parent.mkdir(parents=True, exist_ok=True)
    lsp_config_path.write_text(json.dumps(lsp_config, indent=2), encoding="utf-8")

    logger.info(f"Wrote AL LSP config: {lsp_config_path}")
    logger.debug(f"LSP configuration: {json.dumps(lsp_config, indent=2)}")

    return True
