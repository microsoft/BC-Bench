from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from azure.ai.evaluation.red_team import AttackStrategy, RedTeam, RiskCategory, SupportedLanguages
from azure.identity import DefaultAzureCredential

from bcbench.agent.bcal import BCalBackendConfig, run_bcal_prompt
from bcbench.dataset.dataset_entry import NL2ALEntry
from bcbench.logger import get_logger
from bcbench.operations import ensure_package_cache
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)

__all__ = ["build_bcal_target", "run_scan"]


def build_bcal_target(package_cache_path: Path, export_base: Path, backend_config: BCalBackendConfig) -> Callable[[str], str]:
    """Wrap the nl2al (BCal) as a red-team target callback."""

    category = EvaluationCategory.NL2AL
    entry = category.entry_class.load(category.dataset_path)[0]
    ensure_package_cache(package_cache_path, entry.environment_setup_version)

    def bcal_target(query: str) -> str:
        export_folder = export_base / f"query-{uuid.uuid4().hex[:8]}"
        return run_bcal_prompt(cast(NL2ALEntry, entry), query, package_cache_path, export_folder, backend_config)

    return bcal_target


def run_scan(
    target: Callable[[str], str],
    azure_ai_project: dict[str, str],
    output_path: Path,
    scan_name: str,
    seeds_path: Path | None = None,
    risk_categories: list[RiskCategory] | None = None,
    attack_strategies: list[AttackStrategy] | None = None,
    language: SupportedLanguages | None = None,
    num_objectives: int | None = None,
) -> Path:
    red_team_kwargs: dict[str, Any] = {
        "azure_ai_project": azure_ai_project,
        "credential": DefaultAzureCredential(),
    }
    # Upstream treats custom seeds and risk categories as alternative objective sources.
    if seeds_path is not None:
        red_team_kwargs["custom_attack_seed_prompts"] = str(seeds_path)
    elif risk_categories:
        red_team_kwargs["risk_categories"] = risk_categories
    if language is not None:
        red_team_kwargs["language"] = language
    if num_objectives is not None:
        red_team_kwargs["num_objectives"] = num_objectives

    red_team = RedTeam(**red_team_kwargs)

    scan_kwargs: dict[str, Any] = {"target": target, "output_path": str(output_path)}
    if scan_name:
        scan_kwargs["scan_name"] = scan_name
    if attack_strategies:
        scan_kwargs["attack_strategies"] = attack_strategies

    logger.info(f"Starting red team scan -> {output_path}")
    asyncio.run(red_team.scan(**scan_kwargs))  # ty: ignore[unresolved-attribute]
    logger.info(f"Red team scan complete: {output_path}")
    return output_path
