"""Harvest attack objectives by driving the Azure AI Red Teaming Agent.

Instead of a live end-to-end scan against bcal, we run the red-team agent with a **capturing target**
that records every attack prompt the agent generates (and returns a neutral reply so the agent keeps
producing objectives). Those captured prompts are the harmful objectives; we persist them in the
upstream seed-prompt JSON format so ``RedTeamHarmsSource`` can couch them and expand across vectors.

This reuses the existing BC-Bench red-team integration (``bcbench.redteam.run_scan``) — the same agent
that powers ``bcbench redteam scan`` — as an *objective generator* for the harms pipeline.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from azure.ai.evaluation.red_team import AttackStrategy, RiskCategory, SupportedLanguages

__all__ = ["harvest_objectives"]

logger = logging.getLogger(__name__)

_NEUTRAL_REPLY = "Thanks, noted."
type CapturingTarget = Callable[..., Coroutine[Any, Any, dict[str, object]]]


def _message_content(message: object) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    if not isinstance(content, str):
        raise TypeError("Harms harvesting target messages must contain string content.")
    return content


def _capturing_target(captured: list[str], lock: threading.Lock) -> CapturingTarget:
    async def target(
        messages: list[object],
        stream: bool = False,
        session_state: str | None = None,
        context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if not messages:
            raise ValueError("Harms harvesting target received no messages.")

        query = _message_content(messages[-1])
        with lock:
            captured.append(query)
        return {
            "messages": [{"role": "assistant", "content": _NEUTRAL_REPLY}],
            "stream": stream,
            "session_state": session_state,
            "context": context or {},
        }

    return target


def _to_seed_entries(prompts: list[str], risk_label: str, language: str) -> list[dict[str, object]]:
    # De-dupe while preserving order; the agent can repeat a prompt across strategies.
    seen: dict[str, None] = {}
    for prompt in prompts:
        seen.setdefault(prompt.strip(), None)
    return [
        {
            "metadata": {"lang": language, "target_harms": [{"risk-type": risk_label, "risk-subtype": ""}]},
            "messages": [{"role": "user", "content": content}],
            "modality": "text",
            "source": ["bcbench-harms-harvest"],
            "id": str(i + 1),
        }
        for i, content in enumerate(k for k in seen if k)
    ]


def harvest_objectives(
    azure_ai_project: dict[str, str],
    output_path: Path,
    *,
    risk_categories: list[RiskCategory] | None = None,
    seeds_path: Path | None = None,
    attack_strategies: list[AttackStrategy] | None = None,
    language: SupportedLanguages | None = None,
    scan_name: str = "bcbench-harms-harvest",
    num_objectives: int | None = None,
) -> Path:
    """Harvest a single category/language whose provenance is known for every callback."""
    from azure.ai.evaluation.red_team import SupportedLanguages

    from bcbench.redteam import run_scan

    if seeds_path is not None or not risk_categories or len(risk_categories) != 1:
        raise ValueError("Harvesting requires exactly one risk category and no seeds; callback provenance cannot distinguish multiple sources.")
    language = language or SupportedLanguages.English  # ty: ignore[unresolved-attribute] - SDK's optional-dependency fallback omits enum members.
    risk_label = getattr(risk_categories[0], "value", None)
    language_label = getattr(language, "value", None)
    if not isinstance(risk_label, str) or not isinstance(language_label, str):
        raise TypeError("Risk and language must be supported Azure red-team enum values.")

    captured: list[str] = []
    lock = threading.Lock()

    scan_output = output_path.parent / f"{output_path.stem}-scan"
    scan_output.mkdir(parents=True, exist_ok=True)

    logger.info("Harvesting red-team attack objectives via a capturing target")
    run_scan(
        target=_capturing_target(captured, lock),
        azure_ai_project=azure_ai_project,
        output_path=scan_output,
        scan_name=scan_name,
        seeds_path=seeds_path,
        risk_categories=risk_categories,
        attack_strategies=attack_strategies,
        language=language,
        num_objectives=num_objectives,
    )

    entries = _to_seed_entries(captured, risk_label, language_label)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Harvested {len(entries)} attack objectives -> {output_path}")
    return output_path
