from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, cast

from azure.ai.evaluation.red_team import AttackStrategy, RedTeam, RiskCategory, SupportedLanguages
from azure.identity import DefaultAzureCredential

from bcbench.agent.bcal import BCalBackendConfig, run_bcal_prompt
from bcbench.dataset.dataset_entry import NL2ALEntry
from bcbench.logger import get_logger
from bcbench.operations import copy_symbol_apps
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)

__all__ = ["build_bcal_target", "run_scan"]

type RedTeamCallback = Callable[..., Coroutine[Any, Any, dict[str, object]]]


def _ensure_utf8_file_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers[:]:
        if not isinstance(handler, logging.FileHandler) or handler.encoding == "utf-8":
            continue

        replacement = logging.FileHandler(handler.baseFilename, mode=handler.mode, encoding="utf-8", delay=handler.delay, errors=handler.errors)
        replacement.setLevel(handler.level)
        replacement.setFormatter(handler.formatter)
        for handler_filter in handler.filters:
            replacement.addFilter(handler_filter)

        logger.removeHandler(handler)
        handler.close()
        logger.addHandler(replacement)


def _ensure_package_cache(package_cache_path: Path, version: str) -> None:
    """Guarantee bcal has BC symbols on disk before scanning, mirroring the `run bcal` command.

    The nl2al pipeline builds these via setup_workspace -> copy_symbol_apps, copying from the BCContainerHelper artifacts cache that scripts/Download-BCSymbols.ps1 populates.
    Red teaming has no nl2al entry of its own, so we build the same .alpackages once here using the BC version from the nl2al dataset.
    A pre-populated cache is reused as-is.

    `copy_symbol_apps` always writes into `<dir>/.alpackages`, hence the parent here.
    """
    if any(package_cache_path.glob("*.app")):
        return

    logger.info(f"Populating bcal package cache at {package_cache_path} (BC {version})")
    copy_symbol_apps(package_cache_path.parent, version)


def _message_content(message: object) -> str:
    content = cast(dict[str, object], message).get("content") if isinstance(message, dict) else getattr(message, "content", None)
    if not isinstance(content, str):
        raise TypeError("Red-team target messages must contain string content.")
    return content


def build_bcal_target(package_cache_path: Path, export_base: Path, backend_config: BCalBackendConfig) -> RedTeamCallback:
    """Wrap the nl2al (BCal) as a red-team target callback."""

    category = EvaluationCategory.NL2AL
    # bcal always requires --page/--audience, but red teaming has no dataset entry of its own at the moment.
    entry = category.entry_class.load(category.dataset_path)[0]
    _ensure_package_cache(package_cache_path, entry.environment_setup_version)

    # Azure's simple string callback converts exceptions into assistant responses. Its full
    # async callback contract preserves target failures as scan errors instead.
    async def bcal_target(
        messages: list[object],
        stream: bool = False,
        session_state: str | None = None,
        context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if not messages:
            raise ValueError("Red-team target received no messages.")

        query = _message_content(messages[-1])
        export_folder = export_base / f"query-{uuid.uuid4().hex[:8]}"
        response = await asyncio.to_thread(run_bcal_prompt, cast(NL2ALEntry, entry), query, package_cache_path, export_folder, backend_config)
        return {
            "messages": [{"role": "assistant", "content": response}],
            "stream": stream,
            "session_state": session_state,
            "context": context or {},
        }

    return bcal_target


def run_scan(
    target: RedTeamCallback,
    azure_ai_project: dict[str, str],
    output_path: Path,
    scan_name: str,
    seeds_path: Path | None = None,
    risk_categories: list[RiskCategory] | None = None,
    attack_strategies: list[AttackStrategy] | None = None,
    language: SupportedLanguages | None = None,
    is_agent_target: bool = False,
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

    red_team = RedTeam(**red_team_kwargs)

    # The SDK retries the callback and swallows failures, so keep the last one to explain an
    # empty scan rather than failing a run the SDK recovered from.
    last_target_error: Exception | None = None

    async def tracked_target(
        messages: list[object],
        stream: bool = False,
        session_state: str | None = None,
        context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        nonlocal last_target_error
        # azure-ai-evaluation opens redteam.log with the Windows locale encoding. Switch it
        # after the SDK initializes the scan logger and before it logs Unicode target output.
        _ensure_utf8_file_handlers(logging.getLogger("RedTeamLogger"))
        try:
            return await target(messages=messages, stream=stream, session_state=session_state, context=context)
        except Exception as error:
            last_target_error = error
            logger.warning(f"Red-team target invocation failed: {error}")
            raise

    scan_kwargs: dict[str, Any] = {"target": tracked_target, "output_path": str(output_path), "is_agent_target": is_agent_target}
    if scan_name:
        scan_kwargs["scan_name"] = scan_name
    if attack_strategies:
        scan_kwargs["attack_strategies"] = attack_strategies

    logger.info(f"Starting red team scan -> {output_path}")
    result = asyncio.run(red_team.scan(**scan_kwargs))  # ty: ignore[unresolved-attribute]
    # A non-empty attack list can still be entirely unscored, which the SDK reports as a 0% ASR scorecard.
    if not result.attack_details or not any(detail.get("attack_success") is not None for detail in result.attack_details):
        raise RuntimeError("Red team scan completed without any evaluated attacks. Inspect the scan logs for incomplete objectives.") from last_target_error
    logger.info(f"Red team scan complete: {output_path}")
    return output_path
