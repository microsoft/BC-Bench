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

__all__ = ["DEFAULT_EVALUATORS", "build_eval_dataset", "evaluate_trials"]

logger = get_logger(__name__)

# Evaluators run on every executed trial so direct (UPIA) and indirect (XPIA) trials are comparable:
#   - content_safety: the standard harms (violence / sexual / self-harm / hate).
#   - indirect_attack: XPIA — did the response comply with the injected attacker instruction. On the
#     direct trials this doubles as a UPIA manipulation signal (the attack is the prompt itself).
#   - code_vulnerability: insecure/malicious generated AL (e.g. an exfiltration HTTP hook).
DEFAULT_EVALUATORS = ("content_safety", "indirect_attack", "code_vulnerability")


def build_eval_dataset(trials: list[HarmsTrial], path: Path) -> Path:
    """Write one evaluator row per executed trial.

    ``query`` is the prompt bcal actually received (the harm for direct/UPIA trials, the benign
    trigger for indirect/XPIA trials); ``context`` carries the injected attack. This mirrors what the
    agent saw, so the RAI evaluators judge manipulation of a real turn rather than treating an
    injected payload as the user's own request.
    """
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
                "query": trial.prompt,
                "response": trial.response,
                "context": trial.attack,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _build_evaluators(names: tuple[str, ...], azure_ai_project: dict[str, str], credential: Any) -> dict[str, Any]:  # noqa: ANN401 - SDK objects
    from azure.ai.evaluation import CodeVulnerabilityEvaluator, ContentSafetyEvaluator, IndirectAttackEvaluator

    factory = {
        "content_safety": lambda: ContentSafetyEvaluator(credential=credential, azure_ai_project=azure_ai_project),
        "indirect_attack": lambda: IndirectAttackEvaluator(credential=credential, azure_ai_project=azure_ai_project),
        "code_vulnerability": lambda: CodeVulnerabilityEvaluator(credential=credential, azure_ai_project=azure_ai_project),
    }
    return {name: factory[name]() for name in names}


def evaluate_trials(
    trials: list[HarmsTrial],
    azure_ai_project: dict[str, str],
    results_dir: Path,
    *,
    evaluators: tuple[str, ...] = DEFAULT_EVALUATORS,
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

    upload_project = azure_ai_project if upload else None

    def _run(evaluators_subset: dict[str, Any], project: dict[str, str] | None) -> dict[str, Any]:
        return evaluate(
            data=str(dataset_path),
            evaluators=evaluators_subset,
            evaluator_config={name: evaluator_config[name] for name in evaluators_subset},
            azure_ai_project=project,
            output_path=str(results_dir / "harms_results.json"),
        )

    try:
        result = _run(evaluator_map, upload_project)
    except Exception as exc:
        # A single flaky/unreachable RAI evaluator (e.g. indirect_attack / code_vulnerability timing
        # out) otherwise aborts the whole batch and discards the evaluators that did succeed. Fall
        # back to scoring each evaluator independently and merge whatever we can get.
        logger.warning(f"Combined evaluation failed ({type(exc).__name__}): {exc}. Falling back to per-evaluator scoring so partial results survive.")
        result = _evaluate_per_evaluator(_run, evaluator_map, upload_project)

    _write_result(result, results_dir / "harms_results.json")
    if url := result.get("studio_url"):
        logger.info(f"Foundry studio: {url}")
    if failed := result.get("failed_evaluators"):
        logger.warning(f"Evaluators that did not complete (network/RAI issues): {failed}. Re-run `harms evaluate` when connectivity is restored.")
    return result


def _evaluate_per_evaluator(run: Any, evaluator_map: dict[str, Any], upload_project: dict[str, str] | None) -> dict[str, Any]:  # noqa: ANN401 - SDK objects
    merged: dict[str, Any] = {"metrics": {}, "rows": [], "failed_evaluators": []}
    for name, evaluator in evaluator_map.items():
        try:
            single = run({name: evaluator}, upload_project)
        except Exception as exc:
            logger.warning(f"Evaluator '{name}' failed ({type(exc).__name__}): {exc}. Skipping it; other evaluators still count.")
            merged["failed_evaluators"].append(name)
            continue
        _merge_into(merged, single)
    if not merged["metrics"] and not merged["rows"]:
        raise RuntimeError(f"All evaluators failed: {merged['failed_evaluators']}")
    return merged


def _merge_into(merged: dict[str, Any], single: dict[str, Any]) -> None:
    merged["metrics"].update(single.get("metrics", {}))
    single_rows = single.get("rows", [])
    if not merged["rows"]:
        merged["rows"] = [dict(row) for row in single_rows]
    else:
        for target, source in zip(merged["rows"], single_rows, strict=False):
            target.update({k: v for k, v in source.items() if k.startswith("outputs.")})
    if url := single.get("studio_url"):
        merged.setdefault("studio_url", url)


def _write_result(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def channel_label(channel: HarmsChannel) -> str:
    return "UPIA" if channel is HarmsChannel.DIRECT else "XPIA"
