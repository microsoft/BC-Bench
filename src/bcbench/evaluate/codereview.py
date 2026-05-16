from collections.abc import Callable
from pathlib import Path

from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.logger import get_logger, github_log_group
from bcbench.operations import apply_patch, setup_repo_prebuild
from bcbench.results.codereview import CodeReviewResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

REVIEW_OUTPUT_FILE = "review.json"

__all__ = ["CodeReviewPipeline"]


class CodeReviewPipeline(EvaluationPipeline[CodeReviewEntry]):
    """Pipeline for code-review evaluation category.

    Code review does not require a BC container — the agent reviews a patch
    and produces review comments without building or running tests.
    """

    def setup_workspace(self, entry: CodeReviewEntry, repo_path: Path) -> None:
        """Setup workspace for code review.
        
        For code-review, we only clean/reset the repo. The patch is passed to
        the agent for review but not applied to the working directory.
        """
        setup_repo_prebuild(entry, repo_path)

    def setup(self, context: EvaluationContext[CodeReviewEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[CodeReviewEntry], agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[CodeReviewEntry]) -> None:
        review_output_file: Path = context.repo_path / REVIEW_OUTPUT_FILE

        if review_output_file.exists():
            output = review_output_file.read_text(encoding="utf-8")
        else:
            logger.error(f"No review generated for {context.entry.instance_id}")
            raise RuntimeError(f"No review generated for {context.entry.instance_id}")

        result = CodeReviewResult.create_success(
            context,
            output=output,
            expected_comments=context.entry.expected_comments,
            line_tolerance=context.entry.match_line_tolerance,
        )
        logger.info(f"Parsed {len(result.generated_comments)} comments from {REVIEW_OUTPUT_FILE}")
        logger.info(
            f"Code review metrics: matched={result.matched_comment_count}, "
            f"incorrect={result.incorrect_comment_count}, missed={result.missed_comment_count}, "
            f"precision={result.precision:.3f}, recall={result.recall:.3f}, f1={result.f1:.3f}"
        )
        for comment in result.generated_comments:
            logger.debug(f"  {comment}")
        self.save_result(context, result)
