"""Score harms trials with Azure AI Evaluation safety evaluators and upload the run to Foundry.

Heavy Azure imports are lazy so ``--dry-run`` and unit tests never require the SDK or network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bcbench.harms.case import HarmsChannel
from bcbench.harms.runner import HarmsTrial
from bcbench.logger import get_logger

__all__ = ["build_eval_dataset", "evaluate_trials"]

logger = get_logger(__name__)

# Evaluators whose inputs are (query, response[, context]); both run on every executed trial so
# direct (UPIA) and indirect (XPIA) results are comparable. IndirectAttackEvaluator is XPIA-specific.
_DEFAULT_EVALUATORS = ("content_safety", "indirect_attack")


def build_eval_dataset(trials: list[HarmsTrial], path: Path) -> Path:
    """Write one evaluator row per executed trial. ``query`` is the delivered attack; ``response`` is bcal's output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for trial in trials:
            if not trial.executed:
                continue
            row = {
                "case_id": trial.case_id,
                "vector": trial.vector.value,
                "channel": trial.channel.value,
                "risk": trial.risk,
                "query": trial.attack,
                "response": trial.response,
                "context": trial.attack,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _build_evaluators(names: tuple[str, ...], azure_ai_project: dict[str, str], credential: Any) -> dict[str, Any]:  # noqa: ANN401 - SDK objects
    from azure.ai.evaluation import ContentSafetyEvaluator, IndirectAttackEvaluator

    factory = {
        "content_safety": lambda: ContentSafetyEvaluator(credential=credential, azure_ai_project=azure_ai_project),
        "indirect_attack": lambda: IndirectAttackEvaluator(credential=credential, azure_ai_project=azure_ai_project),
    }
    return {name: factory[name]() for name in names}


def evaluate_trials(
    trials: list[HarmsTrial],
    azure_ai_project: dict[str, str],
    results_dir: Path,
    *,
    evaluators: tuple[str, ...] = _DEFAULT_EVALUATORS,
    upload: bool = True,
) -> dict[str, Any]:
    """Run safety evaluators over the trials and (optionally) upload the run to the Foundry project."""
    dataset_path = build_eval_dataset(trials, results_dir / "eval_dataset.jsonl")
    executed = sum(1 for t in trials if t.executed)
    if executed == 0:
        raise ValueError("No executed trials to evaluate (all trials were dry-run).")

    from azure.ai.evaluation import evaluate
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    evaluator_map = _build_evaluators(evaluators, azure_ai_project, credential)

    # Map dataset columns -> evaluator inputs (context supplied for XPIA-style evaluators that accept it).
    column_mapping = {
        "query": "${data.query}",
        "response": "${data.response}",
        "context": "${data.context}",
    }
    evaluator_config = {name: {"column_mapping": column_mapping} for name in evaluator_map}

    logger.info(f"Evaluating {executed} harms trials with {list(evaluator_map)} (upload={upload})")
    result: dict[str, Any] = evaluate(
        data=str(dataset_path),
        evaluators=evaluator_map,
        evaluator_config=evaluator_config,
        azure_ai_project=azure_ai_project if upload else None,
        output_path=str(results_dir / "harms_results.json"),
    )
    if url := result.get("studio_url"):
        logger.info(f"Foundry studio: {url}")
    return result


def channel_label(channel: HarmsChannel) -> str:
    return "UPIA" if channel is HarmsChannel.DIRECT else "XPIA"
