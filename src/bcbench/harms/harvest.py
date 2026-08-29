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
import threading
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from bcbench.logger import get_logger

__all__ = ["harvest_objectives"]

logger = get_logger(__name__)

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


def _to_seed_entries(prompts: list[str], risk_label: str) -> list[dict[str, object]]:
    # De-dupe while preserving order; the agent can repeat a prompt across strategies.
    seen: dict[str, None] = {}
    for prompt in prompts:
        seen.setdefault(prompt.strip(), None)
    return [
        {
            "metadata": {"lang": "en", "target_harms": [{"risk-type": risk_label, "risk-subtype": ""}]},
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
    risk_categories: list[object] | None = None,
    seeds_path: Path | None = None,
    attack_strategies: list[object] | None = None,
    language: object | None = None,
    scan_name: str = "bcbench-harms-harvest",
    num_objectives: int | None = None,
) -> Path:
    """Run the red-team agent with a capturing target and write generated objectives to ``output_path``.

    Returns the path to the objectives JSON (upstream seed-prompt format). The ``risk_categories`` (or a
    ``seeds_path`` of starting objectives) tell the agent what harms to generate, exactly like
    ``bcbench redteam scan``.
    """
    from bcbench.redteam import run_scan

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

    risk_label = getattr(risk_categories[0], "value", "prohibited_actions") if risk_categories else "prohibited_actions"
    entries = _to_seed_entries(captured, risk_label)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Harvested {len(entries)} attack objectives -> {output_path}")
    return output_path
