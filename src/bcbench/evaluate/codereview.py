import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from bcbench.dataset.codereview import CodeReviewEntry, ReviewComment
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.evaluate.comment_judge import judge_comment_matches
from bcbench.evaluate.review_parsing import parse_review_output
from bcbench.exceptions import PatchApplicationError
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import apply_patch, setup_repo_prebuild
from bcbench.results.codereview import CodeReviewResult, match_comments
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

REVIEW_OUTPUT_FILE = "review.json"

__all__ = ["CodeReviewPipeline"]


def _looks_like_full_file_patch(patch: str) -> bool:
    return "@@" not in patch and "\n--- " in f"\n{patch}" and "\n+++ " in f"\n{patch}"


def _materialize_full_file_patch(repo_path: Path, patch: str) -> list[str]:
    file_count = 0
    current_path: Path | None = None
    current_content: list[str] = []
    materialized_paths: list[str] = []

    def flush_current() -> None:
        nonlocal file_count, current_path, current_content
        if current_path is None:
            return
        current_path.parent.mkdir(parents=True, exist_ok=True)
        current_path.write_text("\n".join(current_content) + "\n", encoding="utf-8")
        materialized_paths.append(current_path.relative_to(repo_path).as_posix())
        file_count += 1
        current_path = None
        current_content = []

    for line in patch.splitlines():
        if line.startswith("--- "):
            flush_current()
            continue

        if line.startswith("+++ "):
            relative_path = re.sub(r"^[ab]/", "", line[4:].strip())
            current_path = repo_path / relative_path
            current_content = []
            continue

        if current_path is None:
            continue

        if line.startswith("+"):
            current_content.append(line[1:])
            continue

        if line.startswith("\\ No newline at end of file"):
            continue

    flush_current()
    return materialized_paths


def _patched_paths(patch: str) -> list[str]:
    return [line[6:].strip() for line in patch.splitlines() if line.startswith("+++ b/")]


class CodeReviewPipeline(EvaluationPipeline[CodeReviewEntry]):
    """Pipeline for code-review evaluation category.

    Code review does not require a BC container. We materialize the dataset patch
    as local git changes so the agent can review the branch diff directly.
    """

    def setup_workspace(self, entry: CodeReviewEntry, repo_path: Path) -> None:
        """Setup workspace for code review by applying the entry patch as local changes."""
        setup_repo_prebuild(entry, repo_path)
        if entry.patch.strip():
            try:
                apply_patch(repo_path, entry.patch, f"{entry.instance_id} review patch")
            except PatchApplicationError:
                if not _looks_like_full_file_patch(entry.patch):
                    raise
                materialized_paths = _materialize_full_file_patch(repo_path, entry.patch)
                if not materialized_paths:
                    raise
                # Mark untracked files as intent-to-add so `git diff HEAD` includes them.
                subprocess.run(["git", "add", "-N", "--", *materialized_paths], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
                logger.info(f"Materialized {len(materialized_paths)} file(s) from simplified review patch for {entry.instance_id}")

            if paths := _patched_paths(entry.patch):
                subprocess.run(
                    ["git", "add", "-N", "--", *paths],
                    cwd=repo_path,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    check=True,
                )
        else:
            logger.warning(f"Entry {entry.instance_id} has empty patch; review will run on clean workspace")

    def setup(self, context: EvaluationContext[CodeReviewEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[CodeReviewEntry], agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
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
            structural_matches = match_comments(
                context.entry.expected_comments,
                generated_comments,
                context.entry.match_line_tolerance,
            )
            validated_matches = judge_comment_matches(
                structural_matches,
                model=context.model,
                work_dir=context.repo_path,
            )
            result = CodeReviewResult.create(
                context,
                output=output,
                expected_comments=context.entry.expected_comments,
                generated_comments=generated_comments,
                line_tolerance=context.entry.match_line_tolerance,
                matched_pairs=validated_matches,
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
