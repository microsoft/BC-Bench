"""LLM-based semantic judge for validating structurally matched code review comment pairs.

After structural matching (file + line proximity), the judge validates whether
each matched pair actually describes the same underlying issue. This filters out
false positives where two comments happen to be near each other but address different concerns.
"""

import json
import re
import subprocess
from pathlib import Path

from bcbench.config import get_config
from bcbench.copilot_cli import find_copilot as _find_copilot
from bcbench.dataset.codereview import ReviewComment
from bcbench.exceptions import LLMJudgeError

_config = get_config()


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


def _build_judge_prompt(pairs: list[tuple[ReviewComment, ReviewComment]], result_path: str) -> str:
    pairs_text = "\n\n".join(_format_pair(i + 1, exp, gen) for i, (exp, gen) in enumerate(pairs))
    return _JUDGE_PROMPT_TEMPLATE.format(pairs_text=pairs_text, result_path=result_path)


def _extract_json_array(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
    if fence:
        stripped = fence.group(1).strip()
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def _parse_judge_results(result_path: Path, num_pairs: int, stdout: str = "") -> list[bool]:
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
    expected_pairs: list[tuple[ReviewComment, ReviewComment]],
    ignored_pairs: list[tuple[ReviewComment, ReviewComment]],
    work_dir: Path,
    model: str = _config.judge.code_review_model,
) -> tuple[list[tuple[ReviewComment, ReviewComment]], list[tuple[ReviewComment, ReviewComment]]]:
    """Judge the expected and ignored structural buckets in a single semantic-judge pass.

    Runs ONE judge subprocess over the concatenation of both buckets, then splits the confirmed
    pairs apart. A single pass keeps scoring to one LLM call per evaluation (less run-to-run
    nondeterminism, one calibration target) and cannot reuse a stale verdict file, since a second
    pass never runs. Defaults to a fixed judge model (``_config.judge.code_review_model``)
    independent of the experiment model, so scores reflect AL review quality rather than a model
    judging itself.

    Expected takes precedence: a generated comment the judge confirms as an expected match is
    dropped from the ignored bucket, so a finding is never both credited as expected and
    neutralized as ignored. Because ignored pairs are matched against every generated comment
    (not only the ones left over after expected structural matching), a finding whose expected
    pair the judge rejects can still be neutralized as ignored instead of counting as a false
    positive.

    Returns:
        ``(validated_expected, validated_ignored)`` — the judge-confirmed subset of each bucket.

    Raises:
        LLMJudgeError: If the judge cannot run or produce a usable verdict. Failing loudly avoids
            silently inflating scores when the judge is broken.
    """
    split = len(expected_pairs)
    verdicts = judge_verdicts(expected_pairs + ignored_pairs, work_dir, model=model)
    validated_expected = [pair for pair, is_match in zip(expected_pairs, verdicts[:split], strict=True) if is_match]
    expected_generated_ids = {id(generated) for _, generated in validated_expected}
    validated_ignored = [pair for pair, is_match in zip(ignored_pairs, verdicts[split:], strict=True) if is_match and id(pair[1]) not in expected_generated_ids]
    return validated_expected, validated_ignored


def judge_verdicts(
    pairs: list[tuple[ReviewComment, ReviewComment]],
    work_dir: Path,
    model: str = _config.judge.code_review_model,
) -> list[bool]:
    """Run the semantic judge over comment pairs and return one match verdict per pair.

    Raises:
        LLMJudgeError: If the judge cannot run or produce a usable verdict.
    """
    if not pairs:
        return []

    copilot_cmd = _find_copilot()
    if not copilot_cmd:
        raise LLMJudgeError("Copilot CLI not found; cannot run the semantic judge")

    result_path = work_dir / _config.judge.result_file
    prompt = " ".join(_build_judge_prompt(pairs, _config.judge.result_file).split())

    try:
        completed = subprocess.run(
            [
                copilot_cmd,
                "--allow-all-tools",
                "--disable-builtin-mcps",
                "--no-custom-instructions",
                f"--model={model}",
                f"--prompt={prompt}",
            ],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_config.timeout.agent_execution,
            check=True,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as exc:
        raise LLMJudgeError(f"Judge subprocess failed: {exc}{_format_subprocess_output(exc)}") from exc

    return _parse_judge_results(result_path, len(pairs), stdout=completed.stdout or "")
