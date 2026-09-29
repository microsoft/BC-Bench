from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from bcbench_core import AgentRunner, EvaluationContext, EvaluationResult, RunIdentity, aggregate_summaries, core_version, execute, load_results, score_results, summarize, write_result
from pydantic import BaseModel


class Task(BaseModel):
    instance_id: str
    text: str
    expected: str


class Answer(EvaluationResult):
    response: str
    expected: str


class UppercasePipeline:
    def evaluate(self, context: EvaluationContext[Task], agent: AgentRunner[EvaluationContext[Task], str]) -> Answer:
        return Answer(
            instance_id=context.instance_id,
            identity=context.identity,
            agent="deterministic",
            model="uppercase",
            response=agent(context),
            expected=context.entry.expected,
        )


class DeterministicAgent:
    def __call__(self, context: EvaluationContext[Task]) -> str:
        return context.entry.text.upper()


class ExactAnswerScorer:
    scorer_id = "exact-answer/v1"

    def __call__(self, result: Answer) -> float:
        return float(result.response == result.expected)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--consumer-revision", required=True)
    args = parser.parse_args()

    identity = RunIdentity(
        core_version=core_version(),
        consumer_revision=args.consumer_revision,
        benchmark_id="synthetic-uppercase/v1",
        data_revision=hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        scorer_id=ExactAnswerScorer.scorer_id,
        experiment={"agent": "deterministic"},
    )
    args.workspace.mkdir(parents=True, exist_ok=True)
    paths = []
    for task in load_results([args.dataset], Task):
        path = args.output_dir / f"{task.instance_id}.jsonl"
        execute(
            EvaluationContext(entry=task, instance_id=task.instance_id, workspace=args.workspace, output_file=path, identity=identity),
            DeterministicAgent(),
            UppercasePipeline(),
        )
        paths.append(path)

    results = load_results(paths, Answer, identity=identity)
    scored = score_results(results, ExactAnswerScorer())
    summary = summarize(scored)
    aggregate = aggregate_summaries([summary])
    write_result(args.output_dir / "summary.jsonl", summary)
    write_result(args.output_dir / "aggregate.jsonl", aggregate)
    print(f"{summary.count} answers round-tripped; mean score {aggregate.mean_score:.1f}")  # noqa: T201 - CLI example output


if __name__ == "__main__":
    main()
