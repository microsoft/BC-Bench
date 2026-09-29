"""First-party code-review composition root; not part of the public library."""

from __future__ import annotations

import argparse
from pathlib import Path

from bcbench.agent import get_copilot_version, run_copilot_agent
from bcbench.config import get_config
from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.results.codereview import CodeReviewResult, CodeReviewResultSummary
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate
from bcbench.results.provenance import make_run_identity
from bcbench.types import AgentHarness, AgentMetrics, EvaluationCategory, EvaluationContext, ExperimentConfiguration
from bcbench_core import AgentRunner, load_results, write_result


def evaluate_code_review(
    *,
    dataset_path: Path,
    entry_id: str,
    repo_path: Path,
    output_dir: Path,
    run_id: str,
    model: str,
    agent_name: AgentHarness,
    agent_version: str | None,
    agent_runner: AgentRunner[EvaluationContext[CodeReviewEntry], tuple[AgentMetrics | None, ExperimentConfiguration | None]],
) -> CodeReviewResultSummary:
    entry = CodeReviewEntry.load(dataset_path, entry_id=entry_id)[0]
    result_path = output_dir / f"{entry.instance_id}{get_config().file_patterns.result_pattern}"
    if result_path.exists():
        raise FileExistsError(f"Use a new output directory for this run: {result_path}")

    context = EvaluationContext(
        entry=entry,
        repo_path=repo_path,
        result_dir=output_dir,
        model=model,
        agent_name=agent_name,
        agent_version=agent_version,
        category=EvaluationCategory.CODE_REVIEW,
        provenance=make_run_identity(EvaluationCategory.CODE_REVIEW, dataset_path),
    )
    CodeReviewPipeline().execute(context, agent_runner)

    results = load_results([result_path], CodeReviewResult)
    summary = CodeReviewResultSummary.from_results(results, run_id)
    summary.save(output_dir, "evaluation_summary.json")
    write_result(output_dir / "aggregate.jsonl", CodeReviewLeaderboardAggregate.from_runs([summary]))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--entry-id", required=True)
    parser.add_argument("--repo-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    summary = evaluate_code_review(
        dataset_path=args.dataset,
        entry_id=args.entry_id,
        repo_path=args.repo_path,
        output_dir=args.output_dir / args.run_id,
        run_id=args.run_id,
        model=args.model,
        agent_name=AgentHarness.COPILOT,
        agent_version=get_copilot_version(),
        agent_runner=lambda context: run_copilot_agent(
            entry=context.entry,
            repo_path=context.repo_path,
            category=EvaluationCategory.CODE_REVIEW,
            model=context.model,
            output_dir=context.result_dir,
        ),
    )
    print(f"Code-review F1: {summary.f1:.3f}")  # noqa: T201 - CLI example output


if __name__ == "__main__":
    main()
