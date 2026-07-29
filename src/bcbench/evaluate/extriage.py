"""Pipeline for the ext-triage category — triage a single extensibility request.

The agent runs the `argus-triage` skill in emit-only mode: it reads the request text from the prompt,
analyses the standard AL source checked out at the entry's base commit, and writes its `Final_Output`
decision (managed labels + advisory comment + open/closed state) to `triage_result.json` in the repo
root instead of applying it via `gh`. Grading is hybrid: exact match on labels and issue state, and an
LLM judge on the advisory comment.
"""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from bcbench.config import get_config
from bcbench.copilot_cli import find_copilot
from bcbench.dataset import ExtTriageEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import LLMJudgeError
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import fetch_commit_if_missing, setup_repo_prebuild
from bcbench.results.extriage import ExtTriageResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)
_config = get_config()

__all__ = ["TRIAGE_RESULT_FILE", "ExtTriagePipeline"]

TRIAGE_RESULT_FILE = "triage_result.json"

_COMMENT_JUDGE_PROMPT = """
You are judging whether a *generated* triage comment on a Business Central extensibility request is an
acceptable substitute for the *expected* comment, given the original request.

Accept the generated comment if it reaches the same triage conclusion and is at least as helpful and
technically accurate as the expected one. Exact wording does not matter; the decision and the actionable
guidance do.

[Request]
{request}

[Expected comment]
{expected}

[Generated comment]
{generated}

Write your verdict to a JSON file at {result_file} using your file-writing tool. The file must contain
ONLY this object: {{"match": true}} or {{"match": false}}. Do not write any other file or prose.
"""


def _normalize_labels(labels: list[str]) -> set[str]:
    return {label.strip().lower() for label in labels if label.strip()}


def _normalize_state(state: str) -> str:
    # An empty ("unchanged") decision leaves an open request open.
    return state.strip().lower() or "open"


def _extract_final_output(raw: str) -> dict:
    data = json.loads(raw)
    if isinstance(data, dict) and isinstance(data.get("Final_Output"), dict):
        return data["Final_Output"]
    if isinstance(data, dict):
        return data
    raise ValueError("triage_result.json is not a JSON object")


def _judge_comment(request: str, expected: str, generated: str, work_dir: Path, model: str) -> bool:
    """Ask a fixed judge model whether the generated comment is an acceptable substitute.

    Empty expected comment means the request should get no comment; that is graded deterministically.
    """
    if not expected.strip():
        return not generated.strip()
    if not generated.strip():
        return False

    copilot_cmd = find_copilot()
    if not copilot_cmd:
        raise LLMJudgeError("Copilot CLI not found; cannot run the triage comment judge")

    result_file = _config.judge.result_file
    prompt = " ".join(_COMMENT_JUDGE_PROMPT.format(request=request, expected=expected, generated=generated, result_file=result_file).split())

    try:
        subprocess.run(
            [copilot_cmd, "--allow-all-tools", "--disable-builtin-mcps", "--no-custom-instructions", f"--model={model}", f"--prompt={prompt}"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_config.timeout.agent_execution,
            check=True,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as exc:
        raise LLMJudgeError(f"Triage comment judge failed: {exc}") from exc

    verdict_path = work_dir / result_file
    if not verdict_path.exists():
        raise LLMJudgeError(f"Triage comment judge produced no verdict file at {verdict_path}")
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    return bool(verdict.get("match", False))


class ExtTriagePipeline(EvaluationPipeline[ExtTriageEntry]):
    """Pipeline for the ext-triage category — no BC container, no build, no tests."""

    def setup_workspace(self, entry: ExtTriageEntry, repo_path: Path) -> None:
        fetch_commit_if_missing(repo_path, entry.base_commit)
        setup_repo_prebuild(entry, repo_path)
        (repo_path / TRIAGE_RESULT_FILE).unlink(missing_ok=True)

    def setup(self, context: EvaluationContext[ExtTriageEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[ExtTriageEntry], agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[ExtTriageEntry]) -> None:
        entry = context.entry
        result_path = context.repo_path / TRIAGE_RESULT_FILE

        if not result_path.exists():
            logger.warning(f"Agent produced no {TRIAGE_RESULT_FILE} for {entry.instance_id}")
            self.save_result(context, ExtTriageResult.create_empty_output(context, error_message=f"No {TRIAGE_RESULT_FILE} produced"))
            return

        raw = result_path.read_text(encoding="utf-8")
        try:
            final_output = _extract_final_output(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"Unparsable {TRIAGE_RESULT_FILE} for {entry.instance_id}: {exc}")
            self.save_result(context, ExtTriageResult.create_empty_output(context, error_message=f"Unparsable {TRIAGE_RESULT_FILE}: {exc}"))
            return

        labels_out = final_output.get("labels_to_set", []) or []
        state_out = str(final_output.get("issue_state", ""))
        comment_out = str(final_output.get("comment_to_post", ""))

        labels_ok = _normalize_labels(labels_out) == _normalize_labels(entry.expected_labels)
        state_ok = _normalize_state(state_out) == _normalize_state(entry.expected_issue_state)

        errors: list[str] = []
        if not labels_ok:
            errors.append(f"Labels: expected {sorted(_normalize_labels(entry.expected_labels))}, got {sorted(_normalize_labels(labels_out))}")
        if not state_ok:
            errors.append(f"State: expected '{_normalize_state(entry.expected_issue_state)}', got '{_normalize_state(state_out)}'")

        try:
            comment_ok = _judge_comment(entry.get_task(), entry.expected_comment, comment_out, context.repo_path, _config.judge.code_review_model)
        except LLMJudgeError as exc:
            logger.warning(f"Comment judge unavailable for {entry.instance_id}: {exc}")
            comment_ok = False
            errors.append(f"Comment judge error: {exc}")
        if not comment_ok and "Comment judge error" not in "".join(errors):
            errors.append("Comment: judge rejected the generated comment")

        logger.info(f"{entry.instance_id}: labels_ok={labels_ok} state_ok={state_ok} comment_ok={comment_ok}")

        result = ExtTriageResult.create(
            context,
            output=raw,
            json_output=raw,
            labels_ok=labels_ok,
            state_ok=state_ok,
            comment_ok=comment_ok,
            error_message="; ".join(errors) or None,
        )
        self.save_result(context, result)
