import logging
import subprocess
from pathlib import Path
from typing import override

from bcbench_core.git import apply_patch, fetch_commit_if_missing

from bcbench.dataset.codereview import CodeReviewEntry, ReviewComment, ReviewCommentKind, Severity
from bcbench.evaluate.base import AgentRunner, EvaluationPipeline
from bcbench.evaluate.codereview_judge import judge_comment_edges
from bcbench.evaluate.review_parsing import parse_review_output
from bcbench.github_actions import github_log_group
from bcbench.operations import setup_repo_prebuild
from bcbench.results.codereview import CodeReviewResult, assign_comment_matches, candidate_comment_pairs
from bcbench.types import EvaluationContext

logger = logging.getLogger(__name__)

REVIEW_OUTPUT_FILE = "review.json"

__all__ = ["CodeReviewPipeline"]


def _patched_paths(patch: str) -> list[str]:
    return [line[6:].strip() for line in patch.splitlines() if line.startswith("+++ b/")]


class CodeReviewPipeline(EvaluationPipeline[CodeReviewEntry]):
    """Pipeline for code-review evaluation category.

    Code review does not require a BC container. We materialize the dataset patch
    as local git changes so the agent can review the branch diff directly.
    """

    minimum_severity = Severity.MEDIUM

    @override
    def setup_workspace(self, entry: CodeReviewEntry, repo_path: Path) -> None:
        """Setup workspace for code review by applying the entry patch as local changes."""
        # Code-review base commits are pre-squash PR commits, so they might be missing from local dev setups.
        fetch_commit_if_missing(repo_path, entry.base_commit)
        setup_repo_prebuild(entry, repo_path)
        apply_patch(repo_path, entry.patch, f"{entry.instance_id} review patch")
        # Mark newly added files as intent-to-add so they appear in `git diff HEAD`;
        # all dataset patches are new-file diffs, which are otherwise untracked and invisible to the agent.
        if paths := _patched_paths(entry.patch):
            subprocess.run(
                ["git", "add", "-N", "--", *paths],
                cwd=repo_path,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
            )

    @override
    def setup(self, context: EvaluationContext[CodeReviewEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    @override
    def run_agent(self, context: EvaluationContext[CodeReviewEntry], agent_runner: AgentRunner[CodeReviewEntry]) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    @override
    def evaluate(self, context: EvaluationContext[CodeReviewEntry]) -> None:
        review_output_file: Path = context.repo_path / REVIEW_OUTPUT_FILE

        if not review_output_file.exists():
            logger.error(f"No review generated for {context.entry.instance_id}")
            raise RuntimeError(f"No review generated for {context.entry.instance_id}")
        output: str = review_output_file.read_text(encoding="utf-8")

        generated_comments: list[ReviewComment] | None = parse_review_output(output)
        mechanical = [comment for comment in context.entry.expected_comments + context.entry.ignored_comments if comment.kind != ReviewCommentKind.REVIEW_FINDING]
        mechanical_ids = {id(comment) for comment in mechanical}
        review_expected = [comment for comment in context.entry.expected_comments if id(comment) not in mechanical_ids]
        original_ignored_comments = [comment for comment in context.entry.ignored_comments if id(comment) not in mechanical_ids] + mechanical
        out_of_scope = [comment for comment in review_expected if comment.severity is not None and comment.severity.level < self.minimum_severity.level]
        excluded_ids = {id(comment) for comment in out_of_scope}
        scoped_expected = [comment for comment in review_expected if id(comment) not in excluded_ids]
        scoped_ignored = original_ignored_comments + out_of_scope

        if generated_comments is None:
            logger.warning(f"Invalid review output for {context.entry.instance_id}")
            original = CodeReviewResult.create_invalid(context, output, review_expected)
            original.ignored_comments = original_ignored_comments
            result = CodeReviewResult.create_invalid(context, output, scoped_expected)
            result.ignored_comments = scoped_ignored
        else:
            expected_candidates = candidate_comment_pairs(context.entry.expected_comments, generated_comments)
            ignored_candidates = candidate_comment_pairs(context.entry.ignored_comments, generated_comments)
            expected_edges, ignored_edges = judge_comment_edges(
                expected_candidates,
                ignored_candidates,
                work_dir=context.repo_path,
            )
            mechanical_edges = [pair for pair in expected_edges + ignored_edges if id(pair[0]) in mechanical_ids]
            review_edges = [pair for pair in expected_edges if id(pair[0]) not in mechanical_ids]
            ignored_edges = [pair for pair in ignored_edges if id(pair[0]) not in mechanical_ids]
            original_matches, original_ignored = assign_comment_matches(review_edges, ignored_edges, repeatable_ignored_pairs=mechanical_edges)
            original = CodeReviewResult.create(
                context,
                output=output,
                expected_comments=review_expected,
                generated_comments=generated_comments,
                matched_pairs=original_matches,
                ignored_comments=original_ignored_comments,
                ignored_matched_pairs=original_ignored,
            )
            # Reassign the SAME semantic verdicts, prioritizing in-scope gold before
            # neutral gold. Never drop a generated comment based on its own severity.
            matched, neutral = assign_comment_matches(
                [pair for pair in review_edges if id(pair[0]) not in excluded_ids],
                ignored_edges + [pair for pair in review_edges if id(pair[0]) in excluded_ids],
                repeatable_ignored_pairs=mechanical_edges,
            )
            result = CodeReviewResult.create(
                context,
                output=output,
                expected_comments=scoped_expected,
                generated_comments=generated_comments,
                matched_pairs=matched,
                ignored_comments=scoped_ignored,
                ignored_matched_pairs=neutral,
            )
            result.out_of_scope_matched_comment_count = sum(id(gold) in excluded_ids for gold, _ in neutral)
            result.mechanical_matched_comment_count = sum(id(gold) in mechanical_ids for gold, _ in neutral)
            original.mechanical_matched_comment_count = sum(id(gold) in mechanical_ids for gold, _ in original_ignored)
        for view in (result, original):
            view.mechanical_diagnostics_neutral = True
            view.mechanical_comments = mechanical
        result.minimum_severity = self.minimum_severity
        result.out_of_scope_comments = out_of_scope
        result.unscoped_result = original
        logger.info(f"Parsed {len(result.generated_comments)} comments from {REVIEW_OUTPUT_FILE}")
        logger.info(
            f"Gold scope >= {self.minimum_severity}: excluded_gold={len(out_of_scope)}, "
            f"neutralized_by_scope={result.out_of_scope_matched_comment_count}; "
            f"mechanical_gold={len(mechanical)}, mechanical_neutral={result.mechanical_matched_comment_count}; "
            f"unscoped matched={original.matched_comment_count}, expected={len(original.expected_comments)}, "
            f"precision={original.precision:.3f}, recall={original.recall:.3f}"
        )
        logger.info(
            f"Code review metrics: matched={result.matched_comment_count}, "
            f"incorrect={result.incorrect_comment_count}, missed={result.missed_comment_count}, "
            f"ignored={result.ignored_matched_comment_count}, "
            f"precision={result.precision:.3f}, recall={result.recall:.3f}, f1={result.f1:.3f}"
        )

        self.save_result(context, result)
