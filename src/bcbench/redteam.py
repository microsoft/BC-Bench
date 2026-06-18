from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from bcbench.agent.bcal import BCalBackendConfig, run_bcal_prompt
from bcbench.dataset.dataset_entry import NL2ALEntry
from bcbench.logger import get_logger

logger = get_logger(__name__)

__all__ = ["build_bcal_target", "run_scan"]


def _ensure_package_cache(package_cache_path: Path, version: str) -> None:
    """Guarantee bcal has BC symbols on disk before scanning, mirroring the working `run bcal`.

    Every bcal call really shells out and reads *.app symbol files from disk, so the cache
    must physically exist. The nl2al pipeline builds it via setup_workspace -> copy_symbol_apps
    (copying from the BCContainerHelper artifacts cache that scripts/Download-BCSymbols.ps1
    populates). Red teaming has no nl2al entry, so we build the same .alpackages once here,
    using the BC version from the nl2al dataset. A pre-populated cache is reused as-is.

    Assumption: package_cache_path is named '.alpackages' (so copy_symbol_apps, which always
    writes into '<dir>/.alpackages', lands exactly here).
    """
    if package_cache_path.exists() and any(package_cache_path.glob("*.app")):
        return

    # Local import: reuse the proven nl2al setup and avoid importing azure-free code at module load.
    from bcbench.operations import copy_symbol_apps

    logger.info(f"Populating bcal package cache at {package_cache_path} (BC {version})")
    copy_symbol_apps(package_cache_path.parent, version)


def build_bcal_target(package_cache_path: Path, export_base: Path, backend_config: BCalBackendConfig) -> Callable[[str], str]:
    """Wrap the nl2al agent (BCal) as a red-team target callback.

    The symbol cache is set up once up front (fail fast before the scan spins up); each
    adversarial query then gets its own export subfolder so concurrent bcal calls — which all
    need real disk access — never collide on generated files. A representative nl2al entry
    supplies the bcal ``--page``/``--audience`` inputs (the adversarial query replaces its prompt).
    """
    from bcbench.types import EvaluationCategory

    category = EvaluationCategory.NL2AL
    entry = category.entry_class.load(category.dataset_path)[0]
    _ensure_package_cache(package_cache_path, entry.environment_setup_version)

    def bcal_target(query: str) -> str:
        export_folder = export_base / f"query-{uuid.uuid4().hex[:8]}"
        return run_bcal_prompt(cast(NL2ALEntry, entry), package_cache_path, export_folder, backend_config)

    return bcal_target


def run_scan(
    *,
    target: Callable[[str], str],
    azure_ai_project: dict[str, str],
    output_path: Path,
    scan_name: str | None = None,
    seeds_path: Path | None = None,
    risk_categories: list[str] | None = None,
    attack_strategies: list[str] | None = None,
    language: str | None = None,
) -> Path:
    # Lazy imports keep azure-ai-evaluation[redteam] an optional dependency.
    from azure.ai.evaluation.red_team import AttackStrategy, RedTeam, RiskCategory, SupportedLanguages
    from azure.identity import DefaultAzureCredential

    red_team_kwargs: dict[str, Any] = {
        "azure_ai_project": azure_ai_project,
        "credential": DefaultAzureCredential(),
    }
    # Upstream treats custom seeds and risk categories as alternative objective sources.
    if seeds_path is not None:
        red_team_kwargs["custom_attack_seed_prompts"] = str(seeds_path)
    elif risk_categories:
        # getattr does member-by-name lookup using the upstream names verbatim (e.g. CodeVulnerability).
        red_team_kwargs["risk_categories"] = [getattr(RiskCategory, rc) for rc in risk_categories]
    if language is not None:
        red_team_kwargs["language"] = getattr(SupportedLanguages, language)

    red_team = RedTeam(**red_team_kwargs)

    scan_kwargs: dict[str, Any] = {"target": target, "output_path": str(output_path)}
    if scan_name:
        scan_kwargs["scan_name"] = scan_name
    if attack_strategies:
        scan_kwargs["attack_strategies"] = [getattr(AttackStrategy, s) for s in attack_strategies]

    logger.info(f"Starting red team scan -> {output_path}")
    asyncio.run(red_team.scan(**scan_kwargs))  # ty: ignore[unresolved-attribute]  # scan() is resolved dynamically by the SDK
    logger.info(f"Red team scan complete: {output_path}")
    return output_path
