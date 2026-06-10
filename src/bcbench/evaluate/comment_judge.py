"""LLM-based semantic judge for validating structurally matched code review comment pairs.

After structural matching (file + line proximity), the judge validates whether
each matched pair actually describes the same underlying issue. This filters out
false positives where two comments happen to be near each other but address different concerns.
"""

import json
import shutil
import subprocess
from pathlib import Path

from bcbench.config import get_config
from bcbench.dataset.codereview import ReviewComment

_config = get_config()

JUDGE_RESULT_FILE = "judge_results.json"

_JUDGE_PROMPT_TEMPLATE = """\
You are a code review evaluation judge. Your task is to determine whether pairs of code review \
comments identify the SAME underlying issue.

For each pair below, decide if the "Expected" and "Candidate" comments point to the same bug, \
concern, or code issue. Accept semantic matches — different wording is fine if it's the same problem.

{pairs_text}

Write your response as a JSON file at {result_path} with the following format:
[{{"pair": 1, "match": true, "reasoning": "brief explanation"}}, ...]

You MUST include a result for every pair. Respond with ONLY the JSON file — no other output or tools.\
"""


def _format_pair(index: int, expected: ReviewComment, generated: ReviewComment) -> str:
    return (
        f"Pair {index}:\n"
        f"  Expected: [{expected.severity}] {expected.file}:{expected.line_start}: {expected.body}\n"
        f"  Candidate: [{generated.severity}] {generated.file}:{generated.line_start}: {generated.body}"
    )


def _build_judge_prompt(pairs: list[tuple[ReviewComment, ReviewComment]], result_path: str) -> str:
    pairs_text = "\n\n".join(_format_pair(i + 1, exp, gen) for i, (exp, gen) in enumerate(pairs))
    return _JUDGE_PROMPT_TEMPLATE.format(pairs_text=pairs_text, result_path=result_path)


def _parse_judge_results(result_path: Path, num_pairs: int) -> list[bool]:
    if not result_path.exists():
        return [True] * num_pairs

    try:
        raw = json.loads(result_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [True] * num_pairs

    if not isinstance(raw, list):
        return [True] * num_pairs

    results_by_pair: dict[int, bool] = {}
    for item in raw:
        if isinstance(item, dict) and "pair" in item and "match" in item:
            results_by_pair[item["pair"]] = bool(item["match"])

    return [results_by_pair.get(i + 1, True) for i in range(num_pairs)]


def _find_copilot() -> str | None:
    return shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")


def judge_comment_matches(
    matched_pairs: list[tuple[ReviewComment, ReviewComment]],
    model: str,
    work_dir: Path,
) -> list[tuple[ReviewComment, ReviewComment]]:
    """Validate structurally matched comment pairs using an LLM semantic judge.

    Args:
        matched_pairs: Pairs from structural matching (expected, generated).
        model: Model name to use for the judge.
        work_dir: Directory to write judge results to.

    Returns:
        Filtered list of pairs where the judge confirmed a semantic match.
    """
    if not matched_pairs:
        return []

    copilot_cmd = _find_copilot()
    if not copilot_cmd:
        return matched_pairs

    result_path = work_dir / JUDGE_RESULT_FILE
    prompt = _build_judge_prompt(matched_pairs, JUDGE_RESULT_FILE)

    try:
        subprocess.run(
            [
                copilot_cmd,
                "--allow-all-tools",
                "--disable-builtin-mcps",
                "--no-custom-instructions",
                f"--model={model}",
                f"--prompt={prompt.replace(chr(10), ' ')}",
            ],
            cwd=str(work_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_config.timeout.agent_execution,
            check=True,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
        return matched_pairs

    verdicts = _parse_judge_results(result_path, len(matched_pairs))
    return [pair for pair, is_match in zip(matched_pairs, verdicts, strict=True) if is_match]
