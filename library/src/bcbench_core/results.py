from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


def core_version() -> str:
    return version("bcbench-core")


class RunIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    core_version: str
    consumer_revision: str
    benchmark_id: str
    data_revision: str
    scorer_id: str
    experiment: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    instance_id: str
    identity: RunIdentity
    agent: str
    model: str


def write_result(path: Path, result: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(result.model_dump_json() + "\n")


def load_results[ResultT: BaseModel](paths: Iterable[Path], result_type: type[ResultT], *, identity: RunIdentity | None = None) -> list[ResultT]:
    results: list[ResultT] = []
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    result = result_type.model_validate_json(line)
                    if identity is not None and getattr(result, "identity", None) != identity:
                        raise ValueError(f"Incompatible result identity in {path}")
                    results.append(result)
    return results


class Scorer[ResultT: EvaluationResult](Protocol):
    @property
    def scorer_id(self) -> str: ...

    def __call__(self, result: ResultT) -> float: ...


class ScoredResult(BaseModel):
    instance_id: str
    score: float
    identity: RunIdentity
    agent: str
    model: str


def score_results[ResultT: EvaluationResult](results: Sequence[ResultT], scorer: Scorer[ResultT]) -> list[ScoredResult]:
    scored = []
    for result in results:
        if result.identity.scorer_id != scorer.scorer_id:
            raise ValueError(f"Result requires scorer {result.identity.scorer_id!r}, got {scorer.scorer_id!r}")
        score = scorer(result)
        if not math.isfinite(score):
            raise ValueError(f"Non-finite score for {result.instance_id}")
        scored.append(ScoredResult(instance_id=result.instance_id, score=score, identity=result.identity, agent=result.agent, model=result.model))
    return scored


class RunSummary(BaseModel):
    identity: RunIdentity
    agent: str
    model: str
    count: int
    mean_score: float
    instance_scores: dict[str, float]


def summarize[SummaryT](
    scored: Sequence[ScoredResult],
    *,
    reducer: Callable[[Sequence[ScoredResult]], SummaryT] | None = None,
) -> RunSummary | SummaryT:
    if not scored:
        raise ValueError("Cannot summarize an empty run")
    first = scored[0]
    if any((row.identity, row.agent, row.model) != (first.identity, first.agent, first.model) for row in scored):
        raise ValueError("Cannot mix identities, agents or models in a summary")
    if reducer is not None:
        return reducer(scored)
    if len({row.instance_id for row in scored}) != len(scored):
        raise ValueError("Duplicate instance IDs in run")
    return RunSummary(
        identity=first.identity,
        agent=first.agent,
        model=first.model,
        count=len(scored),
        mean_score=sum(row.score for row in scored) / len(scored),
        instance_scores={row.instance_id: row.score for row in scored},
    )


def aggregate_summaries[SummaryT: RunSummary, AggregateT](
    summaries: Sequence[SummaryT],
    *,
    reducer: Callable[[Sequence[SummaryT]], AggregateT] | None = None,
) -> RunSummary | AggregateT:
    if not summaries:
        raise ValueError("Cannot aggregate an empty set of runs")
    first = summaries[0]
    if any((run.identity, run.agent, run.model) != (first.identity, first.agent, first.model) for run in summaries):
        raise ValueError("Cannot aggregate incompatible run identities, agents or models")
    if reducer is not None:
        return reducer(summaries)
    count = sum(run.count for run in summaries)
    return RunSummary(
        identity=first.identity,
        agent=first.agent,
        model=first.model,
        count=count,
        mean_score=sum(run.mean_score * run.count for run in summaries) / count,
        instance_scores={key: score for run in summaries for key, score in run.instance_scores.items()},
    )
