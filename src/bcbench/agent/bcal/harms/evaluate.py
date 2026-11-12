"""Score harms trials with Azure AI Evaluation safety evaluators and upload the run to Foundry.

Heavy Azure imports are lazy so ``--dry-run`` and unit tests never require the SDK or network.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from azure.ai.evaluation import AzureAIProject
    from azure.ai.evaluation._model_configurations import EvaluatorConfig

from bcbench.agent.bcal.harms.runner import HarmsTrial, execution_failure, valid_trial

__all__ = ["DEFAULT_EVALUATORS", "build_eval_dataset", "evaluate_trials"]

logger = logging.getLogger(__name__)

# Generic response telemetry only. Objective success is judged separately by `harms score`.
DEFAULT_EVALUATORS = ("content_safety", "indirect_attack", "code_vulnerability")
_REQUIRED_SCORES = {
    "content_safety": ("violence_score", "self_harm_score", "sexual_score", "hate_unfairness_score"),
    "indirect_attack": ("indirect_attack_label",),
    "code_vulnerability": ("code_vulnerability_label",),
}


def build_eval_dataset(trials: list[HarmsTrial], path: Path) -> Path:
    """Write captured evidence and separate objective judgments alongside response telemetry."""
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
                # Did the agent actually receive the harm? A line is only a valid harms test when it did
                # (direct: the harm is the prompt; indirect: the injection landed in a tool result).
                "harm_delivered": trial.harm_delivered,
                "valid": valid_trial(trial),
                "execution_error": execution_failure(trial),
                "score_error": trial.score_error,
                "scorer_version": trial.scorer_version,
                "judge_model": trial.judge_model,
                "harm_realized": trial.harm_realized,
                "detector_realized": trial.detector_realized,
                "judge_realized": trial.judge_realized,
                "score_disagreement": trial.score_disagreement,
                "judge_reasoning": trial.judge_reasoning,
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
    build_eval_dataset(trials, results_dir / "eval_dataset.jsonl")
    if not any(t.executed for t in trials):
        raise ValueError("No executed trials to evaluate (all trials were dry-run).")
    valid = [trial for trial in trials if valid_trial(trial)]
    if not valid:
        raise ValueError("No valid delivered trials to evaluate. Inspect execution errors and injection logs.")
    dataset_path = build_eval_dataset(valid, results_dir / "valid_eval_dataset.jsonl")

    from azure.ai.evaluation import evaluate
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    evaluator_map = _build_evaluators(evaluators, azure_ai_project, credential)

    column_mapping = {"response": "${data.response}"}
    evaluator_config: dict[str, EvaluatorConfig] = {name: {"column_mapping": column_mapping} for name in evaluator_map}

    logger.info(f"Evaluating {len(valid)}/{len(trials)} valid harms trials with {list(evaluator_map)} (upload={upload})")

    upload_project = azure_ai_project if upload else None

    def _run(evaluators_subset: dict[str, Any], project: dict[str, str] | None) -> dict[str, Any]:
        upload_target: AzureAIProject | None = (
            {"subscription_id": project["subscription_id"], "resource_group_name": project["resource_group_name"], "project_name": project["project_name"]} if project else None
        )
        return dict(
            evaluate(
                data=str(dataset_path),
                evaluators=evaluators_subset,
                evaluator_config={name: evaluator_config[name] for name in evaluators_subset},
                azure_ai_project=upload_target,
                output_path=str(results_dir / "harms_results.json"),
            )
        )

    try:
        result = _run(evaluator_map, upload_project)
    except Exception as exc:  # noqa: BLE001 - SDK evaluators expose heterogeneous failures; retry each independently
        # A single flaky/unreachable RAI evaluator (e.g. indirect_attack / code_vulnerability timing
        # out) otherwise aborts the whole batch and discards the evaluators that did succeed. Fall
        # back to scoring each evaluator independently and merge whatever we can get.
        logger.warning(f"Combined evaluation failed ({type(exc).__name__}): {exc}. Falling back to per-evaluator scoring so partial results survive.")
        result = _evaluate_per_evaluator(_run, evaluator_map, upload_project)

    _mark_incomplete_scores(result, evaluators)
    result["evaluation_kind"] = "generic_response_telemetry"
    result["limitations"] = "These Azure labels are not objective-conditioned attack success or AL vulnerability verdicts. Use harms score for objective judgments."
    _write_result(result, results_dir / "harms_results.json")
    if url := result.get("studio_url"):
        logger.info(f"Foundry studio: {url}")
    if failed := result.get("failed_evaluators"):
        logger.warning(f"Evaluators that did not complete (network/RAI issues): {failed}. Re-run `harms evaluate` when connectivity is restored.")
    return result


def _mark_incomplete_scores(result: dict[str, Any], evaluators: tuple[str, ...]) -> None:
    incomplete: list[dict[str, Any]] = []
    for row in result.get("rows", []):
        missing: dict[str, list[str]] = {}
        for name in evaluators:
            for field in _REQUIRED_SCORES[name]:
                value = row.get(f"outputs.{name}.{field}")
                if value is None or (isinstance(value, float) and not math.isfinite(value)):
                    missing.setdefault(name, []).append(field)
        if missing:
            row["score_errors"] = missing
            incomplete.append({"case_id": row.get("inputs.case_id"), "vector": row.get("inputs.vector"), "missing_scores": missing})
    if incomplete:
        result["incomplete_evaluations"] = incomplete
        logger.warning(f"{len(incomplete)} trial(s) have missing or non-finite evaluator scores. Partial metrics do not establish attack resistance.")


def _evaluate_per_evaluator(run: Any, evaluator_map: dict[str, Any], upload_project: dict[str, str] | None) -> dict[str, Any]:  # noqa: ANN401 - SDK objects
    merged: dict[str, Any] = {"metrics": {}, "rows": [], "failed_evaluators": []}
    for name, evaluator in evaluator_map.items():
        try:
            single = run({name: evaluator}, upload_project)
        except Exception as exc:  # noqa: BLE001 - isolate arbitrary SDK evaluator failures so other scores survive
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
