import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.logger import get_logger, github_log_group
from bcbench.operations import setup_repo_prebuild
from bcbench.results.codereview import CodeReviewResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

REVIEW_OUTPUT_FILE = "review.json"
REVIEW_BRANCH_PREFIX = "code-review"

__all__ = ["CodeReviewPipeline"]


def _normalize_diff_path(raw_path: str) -> str:
    normalized = raw_path.strip()
    if normalized.startswith(("a/", "b/")):
        normalized = normalized[2:]
    return normalized.lstrip("/").replace("\\", "/")


def _sanitize_branch_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._/-]+", "-", value).strip("-/") or "entry"


def _checkout_review_branch(repo_path: Path, instance_id: str) -> str:
    branch_name = f"{REVIEW_BRANCH_PREFIX}/{_sanitize_branch_segment(instance_id)}"
    subprocess.run(["git", "checkout", "-B", branch_name], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    return branch_name


def _materialize_files_from_patch(repo_path: Path, patch_content: str) -> list[Path]:
    files_written: list[Path] = []
    lines = patch_content.splitlines()

    current_path: str | None = None
    current_content: list[str] = []

    def flush_current_file() -> None:
        if not current_path:
            return

        target_path = repo_path / current_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text("\n".join(current_content) + "\n", encoding="utf-8")
        files_written.append(target_path)

    for line in lines:
        if line.startswith("--- "):
            flush_current_file()
            current_path = None
            current_content = []
            continue

        if line.startswith("+++ "):
            current_path = _normalize_diff_path(line[4:])
            continue

        if current_path is None:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            current_content.append(line[1:])
            continue

        if line.startswith(" "):
            current_content.append(line[1:])
            continue

        if line.startswith(("-", "@@", "\\ No newline at end of file")):
            continue

    flush_current_file()
    return files_written


def _is_valid_review_payload(payload: object) -> bool:
    if isinstance(payload, dict):
        return isinstance(payload.get("findings"), list)
    return isinstance(payload, list)


def _extract_review_json_candidate(raw_text: str) -> str | None:
    decoder = json.JSONDecoder()

    for match in re.finditer(r"```json\s*([\s\S]*?)\s*```", raw_text, re.IGNORECASE):
        candidate = match.group(1).strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if _is_valid_review_payload(parsed):
            return json.dumps(parsed, ensure_ascii=False)

    for match in re.finditer(r"```\s*([\s\S]*?)\s*```", raw_text):
        candidate = match.group(1).strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if _is_valid_review_payload(parsed):
            return json.dumps(parsed, ensure_ascii=False)

    for idx, ch in enumerate(raw_text):
        if ch not in "[{":
            continue
        try:
            parsed, end_idx = decoder.raw_decode(raw_text[idx:])
        except json.JSONDecodeError:
            continue
        if _is_valid_review_payload(parsed):
            return raw_text[idx : idx + end_idx].strip()

    return None


def _recover_review_output_from_logs(result_dir: Path) -> str | None:
    log_files = sorted(result_dir.glob("process-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)

    for log_file in log_files:
        try:
            content = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        candidate = _extract_review_json_candidate(content)
        if candidate:
            return candidate

    return None


class CodeReviewPipeline(EvaluationPipeline[CodeReviewEntry]):
    """Pipeline for code-review evaluation category.

    Code review does not require a BC container — the agent reviews a patch
    and produces review comments without building or running tests.

    Review flow:
    1. Workspace is reset/cleaned by setup_repo_prebuild and checked out at base commit.
    2. A per-entry branch is created/reset (code-review/<instance_id>).
    3. Files are materialized from dataset patch content in the working tree.
    4. Agent prompt comes from the shared code-review template (currently /review).
    5. Agent writes structured findings to review.json in the repo root.
    6. Pipeline reads review.json and builds a CodeReviewResult for metrics/scoring.
    """

    def setup_workspace(self, entry: CodeReviewEntry, repo_path: Path) -> None:
        """Setup workspace for code review.

        For code-review, we prepare a clean base commit, create/reset a branch
        for the entry, and materialize dataset patch files into the working tree
        so review agents can inspect actual branch changes.
        """
        setup_repo_prebuild(entry, repo_path)
        review_branch = _checkout_review_branch(repo_path, entry.instance_id)
        files_written = _materialize_files_from_patch(repo_path, entry.patch)
        logger.info(f"Prepared review branch {review_branch} with {len(files_written)} materialized file(s)")

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
            recovered_output = _recover_review_output_from_logs(context.result_dir)
            if not recovered_output:
                logger.error(f"No review generated for {context.entry.instance_id}")
                raise RuntimeError(f"No review generated for {context.entry.instance_id}")

            review_output_file.write_text(recovered_output, encoding="utf-8")
            logger.warning(f"Recovered {REVIEW_OUTPUT_FILE} from Copilot logs for {context.entry.instance_id}")
            output = recovered_output

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
