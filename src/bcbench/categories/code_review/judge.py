"""Judge all same-file candidates before assigning one-to-one code review matches."""

import json
import re
import subprocess
from pathlib import Path
from typing import Protocol

from bcbench.categories.code_review.entry import ReviewComment
from bcbench.categories.code_review.results import assign_comment_matches
from bcbench.exceptions import AgentError, LLMJudgeError

type CommentPairs = list[tuple[ReviewComment, ReviewComment]]


class JudgeInvoker(Protocol):
    def __call__(self, *, prompt: str, model: str, work_dir: Path, timeout: int) -> str: ...


_JUDGE_PROMPT_TEMPLATE = """
You are a code review evaluation judge. Your task is to determine whether pairs of code review comments identify the SAME underlying issue.

For each pair below, decide if the "Expected" and "Candidate" comments point to the same bug, concern, or code issue. Accept semantic matches — different wording is fine if it's the same problem.

{pairs_text}

Save your verdict to a JSON file at {result_path} using your file-writing tool. The file must contain ONLY a JSON array in this format:
[{{"pair": 1, "match": true, "reasoning": "brief explanation"}}, ...]

Include exactly one entry for every pair. Do not write any other files or prose.
"""


def _format_pair(index: int, expected: ReviewComment, generated: ReviewComment) -> str:
    return (
        f"Pair {index}:\n"
        f"  Expected: [{expected.severity_label}] {expected.file}:{expected.line_start}: {expected.body}\n"
        f"  Candidate: [{generated.severity_label}] {generated.file}:{generated.line_start}: {generated.body}"
    )


def build_judge_prompt(pairs: CommentPairs, result_path: str) -> str:
    pairs_text = "\n\n".join(_format_pair(i + 1, exp, gen) for i, (exp, gen) in enumerate(pairs))
    return _JUDGE_PROMPT_TEMPLATE.format(pairs_text=pairs_text, result_path=result_path)


def _extract_json_array(text: str) -> str:
    decoder = json.JSONDecoder()
    result: str | None = None
    end = 0
    for token in re.finditer(r'[\[{}\]"]', text):
        if token.start() < end:
            continue
        # Decode whole values; never retry inside a malformed outer value.
        value, end = decoder.raw_decode(text, token.start())
        if not isinstance(value, list):
            raise LLMJudgeError(f"Judge result must be a JSON list, got {type(value).__name__}")
        # Compare all content, including types, but allow JSON formatting differences.
        candidate = json.dumps(value, sort_keys=True)
        if result is not None and candidate != result:
            raise LLMJudgeError("Judge output contains conflicting JSON arrays")
        result = candidate
    return result if result is not None else text.strip()


def parse_judge_results(result_path: Path, num_pairs: int, stdout: str = "") -> list[bool]:
    raw_text = result_path.read_text(encoding="utf-8") if result_path.exists() else stdout
    if not raw_text.strip():
        raise LLMJudgeError(f"Judge produced no result file at {result_path} and no parseable output")

    try:
        raw = json.loads(_extract_json_array(raw_text))
    except (json.JSONDecodeError, OSError) as exc:
        raise LLMJudgeError(f"Judge result is unreadable or not valid JSON: {result_path}") from exc

    if not isinstance(raw, list):
        raise LLMJudgeError(f"Judge result must be a JSON list, got {type(raw).__name__}")

    results_by_pair: dict[int, bool] = {}
    for item in raw:
        if isinstance(item, dict) and "pair" in item and "match" in item:
            results_by_pair[item["pair"]] = bool(item["match"])

    # A pair the judge never returned a verdict for counts as not confirmed.
    return [results_by_pair.get(i + 1, False) for i in range(num_pairs)]


def _decode_stream(stream: str | bytes | None) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream


def _format_subprocess_output(exc: Exception, limit: int = 2000) -> str:
    parts: list[str] = []
    for label in ("stdout", "stderr"):
        text = _decode_stream(getattr(exc, label, None)).strip()
        if text:
            parts.append(f"\n--- {label} ---\n{text[-limit:]}")
    return "".join(parts)


def judge_expected_and_ignored(
    expected_pairs: CommentPairs,
    ignored_pairs: CommentPairs,
    work_dir: Path,
    *,
    invoke: JudgeInvoker,
    model: str,
    timeout: int,
    result_filename: str,
) -> tuple[CommentPairs, CommentPairs]:
    """Judge both candidate buckets once, then assign only confirmed edges one-to-one.

    Maximize expected matches first, ignored matches second, and minimize line distance last.
    The fixed judge model is independent of the experiment model.

    Raises:
        LLMJudgeError: If the judge cannot run or produce a usable verdict.
    """
    split = len(expected_pairs)
    verdicts = judge_verdicts(expected_pairs + ignored_pairs, work_dir, invoke=invoke, model=model, timeout=timeout, result_filename=result_filename)
    validated_expected = [pair for pair, is_match in zip(expected_pairs, verdicts[:split], strict=True) if is_match]
    validated_ignored = [pair for pair, is_match in zip(ignored_pairs, verdicts[split:], strict=True) if is_match]
    return assign_comment_matches(validated_expected, validated_ignored)


def judge_verdicts(
    pairs: CommentPairs,
    work_dir: Path,
    *,
    invoke: JudgeInvoker,
    model: str,
    timeout: int,
    result_filename: str,
) -> list[bool]:
    """Run the semantic judge over comment pairs and return one match verdict per pair.

    Raises:
        LLMJudgeError: If the judge cannot run or produce a usable verdict.
    """
    if not pairs:
        return []

    result_path = work_dir / result_filename
    prompt = " ".join(build_judge_prompt(pairs, result_filename).split())

    try:
        result_path.unlink(missing_ok=True)
        final_response = invoke(
            prompt=prompt,
            model=model,
            work_dir=work_dir,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError, AgentError) as exc:
        raise LLMJudgeError(f"Judge subprocess failed: {exc}{_format_subprocess_output(exc)}") from exc

    return parse_judge_results(result_path, len(pairs), stdout=final_response)
