"""Calibration set for the code-review LLM judge.

A small, hand-labeled set of (expected, candidate) comment pairs with a human verdict on
whether they describe the same underlying issue. Running the judge over this set yields its
precision/recall against human judgement, so judge drift is caught loudly instead of silently
distorting every code-review score.

The non-match cases deliberately share the same file and line as their pair so the judge cannot
pass on location alone — it must discriminate on the issue itself. The match cases deliberately
differ in wording, severity, or line so semantic equivalence is exercised.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bcbench.config import get_config
from bcbench.dataset.codereview import ReviewComment
from bcbench.evaluate.codereview_judge import judge_verdicts
from bcbench.results.metrics import precision_recall
from bcbench.types import JudgeCalibrationReport

_config = get_config()

CALIBRATION_DATASET = _config.paths.dataset_dir / "judge_calibration.jsonl"


@dataclass(frozen=True)
class JudgeCalibrationCase:
    expected: ReviewComment
    candidate: ReviewComment
    should_match: bool
    note: str


def _load_calibration_cases(path: Path = CALIBRATION_DATASET) -> list[JudgeCalibrationCase]:
    cases: list[JudgeCalibrationCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        cases.append(
            JudgeCalibrationCase(
                expected=ReviewComment(**raw["expected"]),
                candidate=ReviewComment(**raw["candidate"]),
                should_match=raw["should_match"],
                note=raw["note"],
            )
        )
    return cases


CALIBRATION_CASES: list[JudgeCalibrationCase] = _load_calibration_cases()


def score_calibration(predicted: list[bool], cases: list[JudgeCalibrationCase] = CALIBRATION_CASES) -> JudgeCalibrationReport:
    if len(predicted) != len(cases):
        raise ValueError(f"Expected {len(cases)} verdicts, got {len(predicted)}")

    tp = fp = tn = fn = 0
    misclassified: list[str] = []
    for verdict, case in zip(predicted, cases, strict=True):
        if verdict and case.should_match:
            tp += 1
        elif verdict and not case.should_match:
            fp += 1
            misclassified.append(f"FALSE POSITIVE: {case.note}")
        elif not verdict and case.should_match:
            fn += 1
            misclassified.append(f"FALSE NEGATIVE: {case.note}")
        else:
            tn += 1

    precision, recall = precision_recall(tp, tp + fp, tp + fn)
    accuracy = (tp + tn) / len(cases) if cases else 0.0

    return JudgeCalibrationReport(
        total=len(cases),
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        accuracy=accuracy,
        misclassified_notes=misclassified,
    )


def run_calibration(work_dir: Path, model: str = _config.judge.model, cases: list[JudgeCalibrationCase] = CALIBRATION_CASES) -> JudgeCalibrationReport:
    """Run the live judge over the calibration set and score it against the human labels.

    Requires the Copilot CLI (raises LLMJudgeError otherwise).
    """
    pairs = [(case.expected, case.candidate) for case in cases]
    verdicts = judge_verdicts(pairs, work_dir, model=model)
    return score_calibration(verdicts, cases)
