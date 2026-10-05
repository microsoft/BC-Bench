"""Category-aware loading and aggregation of evaluation results: picks each category's result, summary and aggregate types."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from bcbench.categories import category_definition
from bcbench.config import JudgeConfig
from bcbench.results import BaseEvaluationResult, EvaluationResultSummary, Leaderboard, LeaderboardAggregate
from bcbench.types import EvaluationCategory


def load_result(payload: dict[str, Any], judges: JudgeConfig) -> BaseEvaluationResult:
    definition = category_definition(EvaluationCategory(payload["category"]))
    # Results from before #822 recorded judge-scored timeouts without the judge model
    if payload.get("timeout") is True and "judge_model" not in payload and (judge_model := definition.judge_model(judges)) is not None:
        payload = {**payload, "judge_model": judge_model}
    return definition.result_type.model_validate(payload)


def summarize_results(results: Sequence[BaseEvaluationResult], run_id: str) -> EvaluationResultSummary:
    return category_definition(results[0].category).summary_type.from_results(results, run_id)


def load_summary(payload: dict[str, Any]) -> EvaluationResultSummary:
    return category_definition(EvaluationCategory(payload["category"])).summary_type.model_validate(payload)


def aggregate_runs(runs: Sequence[EvaluationResultSummary]) -> LeaderboardAggregate:
    if not runs:
        raise ValueError("Cannot create aggregate from empty runs list")
    return category_definition(runs[0].category).aggregate_type.from_runs(runs)


def load_aggregate(payload: dict[str, Any]) -> LeaderboardAggregate:
    return category_definition(EvaluationCategory(payload["category"])).aggregate_type.model_validate(payload)


def load_leaderboard(path: Path) -> Leaderboard:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if not data or not isinstance(data, dict):
        return Leaderboard(runs=[], aggregate=[])
    return Leaderboard(runs=[load_summary(run) for run in data["runs"]], aggregate=[load_aggregate(aggregate) for aggregate in data["aggregate"]])
