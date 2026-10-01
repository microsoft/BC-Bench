from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from bcbench_core.evaluation import EvaluationFlow, EvaluationRequest, EvaluationRun
from bcbench_core.operations import apply_patch, fetch_commit_if_missing, setup_repo_prebuild
from bcbench_core.reporting import JsonlResultWriter

from bcbench.dataset import CodeReviewEntry, ReviewComment
from bcbench.evaluate.codereview_judge import judge_expected_and_ignored
from bcbench.evaluate.review_parsing import parse_review_output
from bcbench.results.codereview import CodeReviewResult, candidate_comment_pairs

REVIEW_OUTPUT_FILE = "review.json"


def _patched_paths(patch: str) -> list[str]:
    return [line[6:].strip() for line in patch.splitlines() if line.startswith("+++ b/")]


@dataclass(frozen=True)
class CodeReviewWorkspace:
    def prepare(self, entry: CodeReviewEntry, repo_path: Path) -> None:
        fetch_commit_if_missing(repo_path, entry.base_commit)
        setup_repo_prebuild(entry, repo_path)
        apply_patch(repo_path, entry.patch, f"{entry.instance_id} review patch")
        if paths := _patched_paths(entry.patch):
            subprocess.run(
                ["git", "add", "-N", "--", *paths],
                cwd=repo_path,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
            )


@dataclass(frozen=True)
class CodeReviewScorer:
    judge_model: str

    def score(self, run: EvaluationRun[CodeReviewEntry]) -> CodeReviewResult:
        if run.execution.timed_out:
            return CodeReviewResult.create_timeout_from_run(run, self.judge_model)

        output_file = run.request.repo_path / REVIEW_OUTPUT_FILE
        if not output_file.exists():
            raise RuntimeError(f"No review generated for {run.request.entry.instance_id}")
        output = output_file.read_text(encoding="utf-8")
        generated_comments: list[ReviewComment] | None = parse_review_output(output)
        if generated_comments is None:
            return CodeReviewResult.create_invalid_from_run(
                run,
                self.judge_model,
                output,
                run.request.entry.expected_comments,
            )

        expected_candidates = candidate_comment_pairs(run.request.entry.expected_comments, generated_comments)
        ignored_candidates = candidate_comment_pairs(run.request.entry.ignored_comments, generated_comments)
        validated_matches, ignored_matches = judge_expected_and_ignored(
            expected_candidates,
            ignored_candidates,
            work_dir=run.request.repo_path,
            model=self.judge_model,
        )
        return CodeReviewResult.create_from_run(
            run,
            self.judge_model,
            output,
            run.request.entry.expected_comments,
            generated_comments,
            matched_pairs=validated_matches,
            ignored_comments=run.request.entry.ignored_comments,
            ignored_matched_pairs=ignored_matches,
        )


@dataclass(frozen=True)
class CodeReviewCategory:
    dataset_path: Path
    prompt_template: str
    judge_model: str

    def load(self, entry_id: str) -> CodeReviewEntry:
        return CodeReviewEntry.load(self.dataset_path, entry_id=entry_id)[0]

    def prompt(self, entry: CodeReviewEntry, repo_path: Path) -> str:
        return self.prompt_template.replace("{{repo_path}}", str(repo_path))

    def request(
        self,
        *,
        entry: CodeReviewEntry,
        repo_path: Path,
        result_dir: Path,
        model: str,
    ) -> EvaluationRequest[CodeReviewEntry]:
        return EvaluationRequest(
            entry=entry,
            repo_path=repo_path,
            result_dir=result_dir,
            result_file=f"{entry.instance_id}.jsonl",
            model=model,
            prompt=self.prompt(entry, repo_path),
        )

    def flow(self) -> EvaluationFlow[CodeReviewEntry, CodeReviewResult]:
        return EvaluationFlow(
            workspace=CodeReviewWorkspace(),
            scorer=CodeReviewScorer(self.judge_model),
            writer=JsonlResultWriter(),
        )
