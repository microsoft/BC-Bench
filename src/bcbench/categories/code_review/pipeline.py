import logging
from collections.abc import Callable
from pathlib import Path

from bcbench.categories.code_review.entry import CodeReviewEntry, ReviewComment
from bcbench.categories.code_review.judge import CommentPairs
from bcbench.categories.code_review.parsing import parse_review_output
from bcbench.categories.code_review.results import CodeReviewResult, candidate_comment_pairs
from bcbench.evaluate.base import AgentRunner, EvaluationPipeline, LogGroup
from bcbench.types import EvaluationContext

logger = logging.getLogger(__name__)

REVIEW_OUTPUT_FILE = "review.json"

__all__ = ["CodeReviewPipeline"]


type WorkspaceSetup = Callable[[CodeReviewEntry, Path], None]
type CommentJudge = Callable[[CommentPairs, CommentPairs, Path], tuple[CommentPairs, CommentPairs]]


class CodeReviewPipeline(EvaluationPipeline[CodeReviewEntry]):
    """Pipeline for code-review evaluation category.

    Code review does not require a BC container. We materialize the dataset patch
    as local git changes so the agent can review the branch diff directly.
    """

    def __init__(self, *, result_suffix: str, setup_workspace: WorkspaceSetup, judge: CommentJudge, log_group: LogGroup | None = None) -> None:
        super().__init__(result_class=CodeReviewResult, result_suffix=result_suffix, log_group=log_group)
        self._setup_workspace = setup_workspace
        self._judge = judge

    def setup_workspace(self, entry: CodeReviewEntry, repo_path: Path) -> None:
        self._setup_workspace(entry, repo_path)

    def setup(self, context: EvaluationContext[CodeReviewEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[CodeReviewEntry], agent_runner: AgentRunner[CodeReviewEntry]) -> None:
        with self.log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[CodeReviewEntry]) -> None:
        review_output_file: Path = context.repo_path / REVIEW_OUTPUT_FILE

        if not review_output_file.exists():
            logger.error(f"No review generated for {context.entry.instance_id}")
            raise RuntimeError(f"No review generated for {context.entry.instance_id}")
        output: str = review_output_file.read_text(encoding="utf-8")

        generated_comments: list[ReviewComment] | None = parse_review_output(output)

        if generated_comments is None:
            logger.warning(f"Invalid review output for {context.entry.instance_id}")
            result = CodeReviewResult.create_invalid(context, output, context.entry.expected_comments)
        else:
            expected_candidates = candidate_comment_pairs(context.entry.expected_comments, generated_comments)
            ignored_candidates = candidate_comment_pairs(context.entry.ignored_comments, generated_comments)
            validated_matches, ignored_matches = self._judge(
                expected_candidates,
                ignored_candidates,
                context.repo_path,
            )
            result = CodeReviewResult.create(
                context,
                output=output,
                expected_comments=context.entry.expected_comments,
                generated_comments=generated_comments,
                matched_pairs=validated_matches,
                ignored_comments=context.entry.ignored_comments,
                ignored_matched_pairs=ignored_matches,
            )
        logger.info(f"Parsed {len(result.generated_comments)} comments from {REVIEW_OUTPUT_FILE}")
        logger.info(
            f"Code review metrics: matched={result.matched_comment_count}, "
            f"incorrect={result.incorrect_comment_count}, missed={result.missed_comment_count}, "
            f"ignored={result.ignored_matched_comment_count}, "
            f"precision={result.precision:.3f}, recall={result.recall:.3f}, f1={result.f1:.3f}"
        )

        self.save_result(context, result)
